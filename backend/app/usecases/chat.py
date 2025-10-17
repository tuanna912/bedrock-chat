import json
import logging
import os
from typing import Callable, Dict
from ulid import ULID
from app.repositories.models.conversation import TextContentModel
from app.agents.tools.agent_tool import AgentTool, ToolRunResult
from app.agents.tools.knowledge import create_knowledge_tool
from app.agents.utils import get_tools
from app.bedrock import (
    call_converse_api,
    compose_args_for_converse_api,
    get_bedrock_runtime_client,
    is_tooluse_supported,
)
from app.prompt import build_rag_prompt, get_prompt_to_cite_tool_results
from app.repositories.conversation import (
    RecordNotFoundError,
    find_conversation_by_id,
    find_conversation_memory,
    store_conversation,
    store_conversation_memory,
    store_related_documents,
)
from app.repositories.conversation_search import find_conversations_by_query
from app.repositories.custom_bot import alias_exists, store_alias
from app.repositories.models.conversation import (
    CompressedContextModel,
    ConversationMemoryModel,
    ConversationModel,
    MessageModel,
    ReasoningContentModel,
    RelatedDocumentModel,
    SimpleMessageModel,
    TextContentModel,
    ToolResultContentModel,
    ToolUseContentModel,
)
from app.repositories.models.custom_bot import (
    BotAliasModel,
    BotModel,
    ConversationQuickStarterModel,
    GenerationParamsModel,
)
from app.routes.schemas.conversation import (
    ChatInput,
    ChatOutput,
    Chunk,
    Conversation,
    ConversationMetaOutput,
    ConversationSearchResult,
    FeedbackOutput,
    MessageOutput,
    SearchHighlight,
    type_model_name,
)
from app.stream import ConverseApiStreamHandler, OnStopInput, OnThinking
from app.usecases.bot import fetch_bot, modify_bot_last_used_time, modify_bot_stats
from app.user import User
from app.utils import get_current_time
from app.vector_search import (
    SearchResult,
    search_related_docs,
    search_result_to_related_document,
    to_guardrails_grounding_source,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================================
# Memory Compression Configuration
# ============================================================================
MEMORY_COMPRESSION_THRESHOLD = int(os.environ.get("MEMORY_COMPRESSION_THRESHOLD", "10"))
RECENT_MESSAGE_FLOOR = 4
logger.info(f"[MEMORY_CONFIG] Memory compression threshold set to: {MEMORY_COMPRESSION_THRESHOLD} messages")


def prepare_conversation(
    user: User,
    chat_input: ChatInput,
) -> tuple[str, ConversationModel, BotModel | None]:
    current_time = get_current_time()
    bot = None

    try:
        # Fetch existing conversation
        conversation = find_conversation_by_id(user.id, chat_input.conversation_id)
        logger.info(f"Found conversation: {conversation}")
        parent_id = chat_input.message.parent_message_id
        if chat_input.message.parent_message_id == "system" and chat_input.bot_id:
            # The case editing first user message and use bot
            parent_id = "instruction"
        elif chat_input.message.parent_message_id is None:
            parent_id = conversation.last_message_id
        if chat_input.bot_id:
            logger.info("Bot id is provided. Fetching bot.")
            owned, bot = fetch_bot(user, chat_input.bot_id)
    except RecordNotFoundError:
        # The case for new conversation. Note that editing first user message is not considered as new conversation.
        logger.info(
            f"No conversation found with id: {chat_input.conversation_id}. Creating new conversation."
        )

        initial_message_map = {
            # Dummy system message, which is used for root node of the message tree.
            "system": MessageModel(
                role="system",
                content=[
                    TextContentModel(
                        content_type="text",
                        body="",
                    )
                ],
                model=chat_input.message.model,
                children=[],
                parent=None,
                create_time=current_time,
                feedback=None,
                used_chunks=None,
                thinking_log=None,
            )
        }
        parent_id = "system"
        if chat_input.bot_id:
            logger.info("Bot id is provided. Fetching bot.")
            parent_id = "instruction"
            # Fetch bot and append instruction
            owned, bot = fetch_bot(user, chat_input.bot_id)
            initial_message_map["instruction"] = MessageModel(
                role="instruction",
                content=[
                    TextContentModel(
                        content_type="text",
                        body=bot.instruction,
                    )
                ],
                model=chat_input.message.model,
                children=[],
                parent="system",
                create_time=current_time,
                feedback=None,
                used_chunks=None,
                thinking_log=None,
            )
            initial_message_map["system"].children.append("instruction")

            if not owned:
                try:
                    # Check alias is already created
                    alias_exists(user.id, chat_input.bot_id)
                except RecordNotFoundError:
                    logger.info(
                        "Bot is not owned by the user. Creating alias to shared bot."
                    )
                    # Create alias item
                    store_alias(user.id, BotAliasModel.from_bot_for_initial_alias(bot))

        # Create new conversation
        conversation = ConversationModel(
            id=chat_input.conversation_id,
            title="New conversation",
            total_price=0.0,
            create_time=current_time,
            message_map=initial_message_map,
            last_message_id="",
            bot_id=chat_input.bot_id,
            should_continue=False,
        )

    # Append user chat input to the conversation
    if not chat_input.continue_generate:
        new_message = MessageModel.from_message_input(chat_input.message)
        new_message.parent = parent_id
        new_message.create_time = current_time

        if chat_input.message.message_id:
            message_id = chat_input.message.message_id
        else:
            message_id = str(ULID())

        conversation.message_map[message_id] = new_message
        conversation.message_map[parent_id].children.append(message_id)  # type: ignore

    # If the "Generate continue" button is pressed, a new_message is not generated.
    else:
        message_id = (
            conversation.message_map[conversation.last_message_id].parent
            or "instruction"
        )

    return (message_id, conversation, bot)


def trace_to_root(
    node_id: str | None, message_map: dict[str, MessageModel]
) -> list[SimpleMessageModel]:
    """Trace message map from leaf node to root node."""
    result: list[SimpleMessageModel] = []
    if not node_id or node_id == "system":
        node_id = "instruction" if "instruction" in message_map else "system"

    current_node = message_map.get(node_id)
    while current_node:
        result.append(SimpleMessageModel.from_message_model(message=current_node))
        if current_node.thinking_log:
            result.extend(
                log
                for log in reversed(current_node.thinking_log)
                if any(
                    isinstance(content, ToolUseContentModel)
                    or isinstance(content, ToolResultContentModel)
                    for content in log.content
                )
            )

        parent_id = current_node.parent
        if parent_id is None:
            break
        current_node = message_map.get(parent_id)

    return result[::-1]


# ============================================================================
# Memory Compression Helpers
# ============================================================================

def compress_contexts_with_bedrock(contexts_to_compress: list, level: int, conversation_id: str):
    """
    Use Claude 3.5 Sonnet to summarize contexts.
    
    Args:
        contexts_to_compress: List of contexts (messages or summaries)
        level: Target compression level
        conversation_id: Conversation ID for logging
    
    Returns:
        CompressedContextModel with the summary
    """
    logger.info(f"[MEMORY_COMPRESSION] Starting compression for conversation_id={conversation_id}")
    logger.info(f"[MEMORY_COMPRESSION] Compressing {len(contexts_to_compress)} contexts from level {level} to level {level+1}")
    logger.info(f"[MEMORY_COMPRESSION] Context IDs: {[ctx.context_id for ctx in contexts_to_compress]}")
    logger.info(f"[MEMORY_COMPRESSION] Message index range: {contexts_to_compress[0].message_index} to {contexts_to_compress[-1].message_index}")
    
    # Build prompt based on what we're compressing
    if level == 0:
        # Compressing original messages (Level 0 → Level 1)
        messages_text = "\n\n".join([
            f"[Message {ctx.message_index}]: {ctx.summary}"
            for ctx in contexts_to_compress
        ])
        prompt = f"""Summarize the following conversation messages into a concise summary that preserves key information:

{messages_text}

Provide a clear, concise summary (max 300 tokens) that captures the main points and context."""
    else:
        # Compressing summaries (Level N → Level N+1)
        summaries_text = "\n\n".join([
            f"[Summary {i+1}]: {ctx.summary}"
            for i, ctx in enumerate(contexts_to_compress)
        ])
        prompt = f"""Consolidate the following conversation summaries into a higher-level summary:

{summaries_text}

Provide a consolidated summary (max 300 tokens) that captures the overall flow and key information."""
    
    # Call Bedrock
    try:
        logger.info(f"[MEMORY_COMPRESSION] Calling Bedrock model: anthropic.claude-3-5-sonnet-20240620-v1:0")
        logger.info(f"[MEMORY_COMPRESSION] Prompt length: {len(prompt)} characters")
        
        client = get_bedrock_runtime_client()
        response = client.invoke_model(
            modelId="anthropic.claude-3-5-sonnet-20240620-v1:0",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1500,
                "temperature": 0.2,
                "messages": [{
                    "role": "user",
                    "content": prompt
                }]
            }),
            contentType="application/json",
            accept="application/json"
        )
        
        response_body = json.loads(response["body"].read())
        summary = response_body["content"][0]["text"].strip()
        
        logger.info(f"[MEMORY_COMPRESSION] Successfully generated summary: {len(summary)} characters")
        logger.info(f"[MEMORY_COMPRESSION] Summary preview: {summary[:200]}...")
        
        # Create compressed context
        start_idx = contexts_to_compress[0].message_index
        end_idx = contexts_to_compress[-1].message_index
        total_messages = sum(ctx.message_count for ctx in contexts_to_compress)
        
        compressed_context_id = str(ULID())
        logger.info(f"[MEMORY_COMPRESSION] Creating compressed context_id={compressed_context_id}")
        logger.info(f"[MEMORY_COMPRESSION] Compressed level={level + 1}, message_index={start_idx}, message_count={total_messages}")
        
        compressed = CompressedContextModel(
            context_id=compressed_context_id,
            level=level + 1,
            message_index=start_idx,
            summary=summary,
            message_count=total_messages,
            create_time=get_current_time()
        )
        
        logger.info(f"[MEMORY_COMPRESSION] Compression completed successfully for level {level+1}")
        return compressed
        
    except Exception as e:
        logger.error(f"[MEMORY_COMPRESSION] ERROR - Failed to compress contexts for conversation_id={conversation_id}: {str(e)}", exc_info=True)
        logger.error(f"[MEMORY_COMPRESSION] ERROR - Level: {level}, Contexts count: {len(contexts_to_compress)}")
        raise


def process_memory_compression(user_id: str, conversation: ConversationModel):
    """
    Process memory compression for conversation.
    
    Logic:
    - Each message = 1 Level 0 context
    - Every 10 Level 0 contexts → compress to 1 Level 1 context
    - Every 10 Level N contexts → compress to 1 Level N+1 context (recursive)
    """
    logger.info(f"[MEMORY_COMPRESSION] ========== Starting Memory Compression Process ==========")
    logger.info(f"[MEMORY_COMPRESSION] user_id={user_id}, conversation_id={conversation.id}")
    
    # Get or create memory
    memory = find_conversation_memory(user_id, conversation.id)
    if memory is None:
        logger.info(f"[MEMORY_COMPRESSION] No existing memory found. Creating new ConversationMemoryModel")
        memory = ConversationMemoryModel(
            conversation_id=conversation.id,
            contexts_by_level={},
            total_message_count=0,
            last_compression_time=None
        )
    else:
        logger.info(f"[MEMORY_COMPRESSION] Found existing memory: total_message_count={memory.total_message_count}")
        logger.info(f"[MEMORY_COMPRESSION] Existing levels: {list(memory.contexts_by_level.keys())}")
        for level, contexts in memory.contexts_by_level.items():
            logger.info(f"[MEMORY_COMPRESSION] Level {level}: {len(contexts)} contexts")
    
    # Count current messages in conversation
    message_count = 0
    for msg_id, msg in conversation.message_map.items():
        if msg.role in ["user", "assistant"]:
            message_count += 1
    
    logger.info(f"[MEMORY_COMPRESSION] Total messages in conversation: {message_count}")
    
    # Check if we need compression
    pending_messages = message_count - memory.total_message_count
    
    logger.info(f"[MEMORY_COMPRESSION] Pending messages to process: {pending_messages}")
    
    if pending_messages < MEMORY_COMPRESSION_THRESHOLD:
        logger.info(f"[MEMORY_COMPRESSION] Only {pending_messages} pending messages, threshold is {MEMORY_COMPRESSION_THRESHOLD}. Skipping compression")
        logger.info(f"[MEMORY_COMPRESSION] ========== Memory Compression Process Completed (No Action) ==========")
        return memory
    
    logger.info(f"[MEMORY_COMPRESSION] Threshold met! Processing compression for {pending_messages} pending messages (threshold: {MEMORY_COMPRESSION_THRESHOLD})")
    
    # Add new messages as Level 0 contexts
    logger.info(f"[MEMORY_COMPRESSION] Step 1: Adding new messages as Level 0 contexts")
    messages_list = []
    for msg_id, msg in conversation.message_map.items():
        if msg.role in ["user", "assistant"]:
            messages_list.append((msg_id, msg))
    
    # Sort by create_time
    messages_list.sort(key=lambda x: x[1].create_time)
    logger.info(f"[MEMORY_COMPRESSION] Total messages sorted by create_time: {len(messages_list)}")
    
    # Get messages that need to be added as Level 0 contexts
    new_messages = messages_list[memory.total_message_count:]
    logger.info(f"[MEMORY_COMPRESSION] New messages to add as Level 0 contexts: {len(new_messages)}")
    
    for idx, (msg_id, msg) in enumerate(new_messages):
        # Extract text content

        text_content = ""
        for content in msg.content:
            if isinstance(content, TextContentModel):
                text_content += content.body
        
        if not text_content:
            text_content = f"[{msg.role} message]"
        
        context_id = str(ULID())
        message_idx = memory.total_message_count + idx
        logger.info(f"[MEMORY_COMPRESSION] Creating Level 0 context [{idx+1}/{len(new_messages)}]: context_id={context_id}, message_index={message_idx}, role={msg.role}")
        logger.info(f"[MEMORY_COMPRESSION] Content preview: {text_content[:100]}...")
        
        # Create Level 0 context
        ctx = CompressedContextModel(
            context_id=context_id,
            level=0,
            message_index=message_idx,
            summary=f"{msg.role.upper()}: {text_content[:500]}",  # Truncate if too long
            message_count=1,
            create_time=msg.create_time
        )
        memory.add_context(ctx)
    
    memory.total_message_count = message_count
    memory.last_compression_time = get_current_time()
    logger.info(f"[MEMORY_COMPRESSION] Updated total_message_count to {memory.total_message_count}")
    logger.info(f"[MEMORY_COMPRESSION] Level 0 now has {len(memory.get_level_contexts(0))} contexts")
    
    # Recursive compression for all levels
    logger.info(f"[MEMORY_COMPRESSION] Step 2: Starting recursive compression")
    current_level = 0
    compression_rounds = 0
    
    while memory.should_compress_level(current_level, threshold=MEMORY_COMPRESSION_THRESHOLD):
        compression_rounds += 1
        level_context_count = len(memory.get_level_contexts(current_level))
        logger.info(f"[MEMORY_COMPRESSION] Compression Round {compression_rounds}: Level {current_level} has {level_context_count} contexts (threshold: {MEMORY_COMPRESSION_THRESHOLD})")
        
        level_contexts = memory.get_level_contexts(current_level)
        contexts_to_compress = level_contexts[:MEMORY_COMPRESSION_THRESHOLD]
        
        logger.info(f"[MEMORY_COMPRESSION] Compressing {MEMORY_COMPRESSION_THRESHOLD} Level {current_level} contexts → 1 Level {current_level+1} context")
        
        # Compress these 10 contexts into 1 higher-level context
        compressed = compress_contexts_with_bedrock(
            contexts_to_compress=contexts_to_compress,
            level=current_level,
            conversation_id=conversation.id
        )
        
        memory.add_context(compressed)
        logger.info(f"[MEMORY_COMPRESSION] Successfully added compressed context to Level {current_level+1}")
        
        # Remove compressed contexts from current level
        memory.contexts_by_level[current_level] = level_contexts[MEMORY_COMPRESSION_THRESHOLD:]
        remaining_contexts = len(memory.contexts_by_level[current_level])
        logger.info(f"[MEMORY_COMPRESSION] Removed {MEMORY_COMPRESSION_THRESHOLD} compressed contexts from Level {current_level}. Remaining: {remaining_contexts}")
        
        # Move to next level
        current_level += 1
        logger.info(f"[MEMORY_COMPRESSION] Moving to next level: {current_level}")
    
    logger.info(f"[MEMORY_COMPRESSION] Compression rounds completed: {compression_rounds}")
    logger.info(f"[MEMORY_COMPRESSION] Final memory structure:")
    for level, contexts in memory.contexts_by_level.items():
        logger.info(f"[MEMORY_COMPRESSION]   Level {level}: {len(contexts)} contexts")
    
    # Store updated memory
    logger.info(f"[MEMORY_COMPRESSION] Step 3: Storing updated memory to DynamoDB")
    store_conversation_memory(user_id, memory)
    logger.info(f"[MEMORY_COMPRESSION] Memory successfully stored to DynamoDB")
    logger.info(f"[MEMORY_COMPRESSION] ========== Memory Compression Process Completed Successfully ==========")
    
    return memory


def build_context_from_memory(
    user_id: str,
    conversation: ConversationModel,
    prefetched_memory: ConversationMemoryModel | None = None,
) -> str:
    """
    Build context string from compressed memory to prepend to messages.
    
    Returns:
        Context string to add to prompt
    """
    logger.info(f"[MEMORY_CONTEXT] Building context from memory for conversation_id={conversation.id}")
    
    memory = prefetched_memory
    if memory is None:
        logger.info(f"[MEMORY_CONTEXT] No prefetched memory provided. Fetching from DynamoDB.")
        memory = find_conversation_memory(user_id, conversation.id)
    else:
        logger.info(f"[MEMORY_CONTEXT] Using prefetched memory object.")
    
    if memory is None or not memory.contexts_by_level:
        logger.info(f"[MEMORY_CONTEXT] No memory or contexts found. Returning empty context")
        return ""
    
    logger.info(f"[MEMORY_CONTEXT] Memory found with {len(memory.contexts_by_level)} levels")
    for level, contexts in memory.contexts_by_level.items():
        logger.info(f"[MEMORY_CONTEXT] Level {level}: {len(contexts)} contexts")
    
    context_parts = ["=== CONVERSATION HISTORY ===\n"]
    
    # Collect contexts for prompt, skipping raw Level 0 events (these remain in real messages)
    contexts_for_prompt: list[CompressedContextModel] = []
    skipped_level0 = 0
    for level, contexts in memory.contexts_by_level.items():
        if level == 0:
            skipped_level0 += len(contexts)
            continue
        contexts_for_prompt.extend(contexts)
    
    if skipped_level0:
        logger.info(f"[MEMORY_CONTEXT] Skipping {skipped_level0} Level 0 contexts; latest messages stay uncompressed in prompt")

    if not contexts_for_prompt:
        logger.info(f"[MEMORY_CONTEXT] No compressed contexts (level >=1) available. Returning empty context")
        return ""

    contexts_for_prompt.sort(key=lambda ctx: ctx.message_index)
    logger.info(f"[MEMORY_CONTEXT] Total contexts to include: {len(contexts_for_prompt)}")
    
    # Add contexts from all levels
    context_count = 0
    for ctx in contexts_for_prompt:
        context_count += 1
        msg_range = f"{ctx.message_index}-{ctx.message_index + ctx.message_count - 1}"
        logger.info(f"[MEMORY_CONTEXT] Adding Level {ctx.level} summary [{context_count}/{len(contexts_for_prompt)}]: messages {msg_range}")
        context_parts.append(f"\n[Messages {msg_range} Summary]:")
        context_parts.append(ctx.summary)
    
    if len(context_parts) == 1:  # Only header, no contexts
        logger.info(f"[MEMORY_CONTEXT] No contexts added. Returning empty context")
        return ""
    
    context_parts.append("\n=== END HISTORY ===\n")
    final_context = "\n".join(context_parts)
    logger.info(f"[MEMORY_CONTEXT] Context built successfully: {len(final_context)} characters")
    
    return final_context


def prune_messages_with_memory(
    messages: list[SimpleMessageModel],
    memory: ConversationMemoryModel,
) -> list[SimpleMessageModel]:
    """
    Remove older user/assistant messages from the prompt once they have been
    summarized into higher-level contexts.
    """
    has_compressed_levels = any(
        level > 0 and contexts for level, contexts in memory.contexts_by_level.items()
    )
    if not has_compressed_levels:
        logger.info("[MEMORY_PROMPT] No compressed contexts available. Keeping full conversation history.")
        return messages

    user_like_indices = [
        idx
        for idx, message in enumerate(messages)
        if message.role in {"user", "assistant"}
    ]
    if not user_like_indices:
        logger.info("[MEMORY_PROMPT] No user/assistant messages detected in prompt. Skipping pruning.")
        return messages

    remaining_level0 = len(memory.get_level_contexts(0))
    keep_recent_target = max(remaining_level0, RECENT_MESSAGE_FLOOR)
    keep_recent_target = min(keep_recent_target, MEMORY_COMPRESSION_THRESHOLD)
    keep_recent_target = min(keep_recent_target, len(user_like_indices))

    drop_count = len(user_like_indices) - keep_recent_target
    if drop_count <= 0:
        logger.info(
            "[MEMORY_PROMPT] Prompt already within recent message window. Nothing to prune."
        )
        return messages

    logger.info(
        f"[MEMORY_PROMPT] Pruning {drop_count} historical user/assistant messages "
        f"(keeping {keep_recent_target} of {len(user_like_indices)} most recent)."
    )

    indices_to_keep = set(user_like_indices[-keep_recent_target:])
    trimmed: list[SimpleMessageModel] = []
    pruned = 0

    for idx, message in enumerate(messages):
        if message.role in {"user", "assistant"} and idx not in indices_to_keep:
            pruned += 1
            continue
        trimmed.append(message)

    logger.info(
        f"[MEMORY_PROMPT] Prompt messages reduced from {len(messages)} to {len(trimmed)} "
        f"(removed {pruned} user/assistant entries)."
    )
    return trimmed


def chat(
    user: User,
    chat_input: ChatInput,
    on_stream: Callable[[str], None] | None = None,
    on_stop: Callable[[OnStopInput], None] | None = None,
    on_thinking: Callable[[OnThinking], None] | None = None,
    on_tool_result: Callable[[ToolRunResult], None] | None = None,
    on_reasoning: Callable[[str], None] | None = None,
) -> tuple[ConversationModel, MessageModel]:
    user_msg_id, conversation, bot = prepare_conversation(user, chat_input)

    memory: ConversationMemoryModel | None = None
    # Process memory compression after adding user message
    logger.info(f"[MEMORY_CHAT] Starting memory compression for conversation_id={conversation.id}")
    try:
        memory = process_memory_compression(user.id, conversation)
        logger.info(f"[MEMORY_CHAT] Memory compression processed successfully for conversation {conversation.id}")
        logger.info(f"[MEMORY_CHAT] Memory stats: total_message_count={memory.total_message_count}, levels={list(memory.contexts_by_level.keys())}")
        
        # Build context from compressed memory
        compressed_context = build_context_from_memory(user.id, conversation, memory)
        if compressed_context:
            logger.info(f"[MEMORY_CHAT] Adding {len(compressed_context)} chars of compressed context to prompt")
            # Context will be prepended to system prompt later
        else:
            logger.info(f"[MEMORY_CHAT] No compressed context to add")
    except Exception as e:
        logger.error(f"[MEMORY_CHAT] Memory compression failed, continuing without compression: {str(e)}", exc_info=True)
        compressed_context = ""
        memory = None

    # # Set tools only when tooluse is supported
    tools: Dict[str, AgentTool] = {}
    if is_tooluse_supported(chat_input.message.model):
        tools = get_tools(bot)

    display_citation = bot is not None and bot.display_retrieved_chunks

    message_map = conversation.message_map
    instructions: list[str] = (
        [
            content.body
            for content in message_map["instruction"].content
            if isinstance(content, TextContentModel)
        ]
        if "instruction" in message_map
        else []
    )

    # Add compressed context to instructions
    if compressed_context:
        instructions.append(compressed_context)

    related_documents: list[RelatedDocumentModel] = []
    search_results: list[SearchResult] = []
    if bot is not None:
        if bot.is_agent_enabled() and is_tooluse_supported(chat_input.message.model):
            # If it have a knowledge base, always process it in agent mode
            if bot.has_knowledge():
                # Add knowledge tool
                knowledge_tool = create_knowledge_tool(bot=bot)
                tools[knowledge_tool.name] = knowledge_tool

            if display_citation:
                instructions.append(
                    get_prompt_to_cite_tool_results(
                        model=chat_input.message.model,
                    )
                )
        elif bot.has_knowledge() and not is_tooluse_supported(chat_input.message.model):
            # Fetch most related documents from vector store
            # NOTE: Currently embedding not support multi-modal. For now, use the last content.
            content = conversation.message_map[user_msg_id].content[-1]
            if isinstance(content, TextContentModel):
                pseudo_tool_use_id = "new-message-assistant"

                if on_thinking:
                    on_thinking(
                        {
                            "tool_use_id": pseudo_tool_use_id,
                            "name": "knowledge_base_tool",
                            "input": {
                                "query": content.body,
                            },
                        }
                    )

                search_results = search_related_docs(bot=bot, query=content.body)
                logger.info(f"Search results from vector store: {search_results}")

                if on_tool_result:
                    on_tool_result(
                        {
                            "tool_use_id": pseudo_tool_use_id,
                            "status": "success",
                            "related_documents": [
                                search_result_to_related_document(
                                    search_result=result,
                                    source_id_base=pseudo_tool_use_id,
                                )
                                for result in search_results
                            ],
                        }
                    )

                # Insert contexts to instruction
                instructions.append(
                    build_rag_prompt(
                        search_results=search_results,
                        model=chat_input.message.model,
                        display_citation=display_citation,
                    )
                )

    # Leaf node id
    # If `continue_generate` is True, note that new message is not added to the message map.
    node_id = (
        chat_input.message.parent_message_id
        if chat_input.continue_generate
        else message_map[user_msg_id].parent
    )
    if node_id is None:
        raise ValueError("parent_message_id or parent is None")

    messages = trace_to_root(
        node_id=node_id,
        message_map=message_map,
    )

    continue_generate = chat_input.continue_generate

    if continue_generate:
        message_for_continue_generate = SimpleMessageModel.from_message_model(
            message=message_map[conversation.last_message_id],
        )

    else:
        messages.append(
            SimpleMessageModel.from_message_model(message=message_map[user_msg_id]),
        )
        message_for_continue_generate = None

    if memory is not None:
        original_len = len(messages)
        messages = prune_messages_with_memory(messages, memory)
        logger.info(
            f"[MEMORY_PROMPT] Messages passed to model: {original_len} -> {len(messages)} entries after pruning."
        )

    generation_params = bot.generation_params if bot else None

    # Guardrails
    guardrail = bot.bedrock_guardrails if bot else None
    grounding_source = None
    if guardrail and guardrail.is_guardrail_enabled:
        grounding_source = to_guardrails_grounding_source(search_results)

    stream_handler = ConverseApiStreamHandler(
        model=chat_input.message.model,
        instructions=instructions,
        generation_params=generation_params,
        guardrail=guardrail,
        tools=tools,
        on_stream=on_stream,
        on_thinking=on_thinking,
        on_reasoning=on_reasoning,
    )

    thinking_log: list[SimpleMessageModel] = []
    while True:
        result = stream_handler.run(
            messages=messages,
            grounding_source=grounding_source,
            message_for_continue_generate=message_for_continue_generate,
            enable_reasoning=chat_input.enable_reasoning,
            prompt_caching_enabled=(
                bot.prompt_caching_enabled if bot is not None else True
            ),
        )

        message = result["message"]
        stop_reason = result["stop_reason"]

        conversation.total_price += result["price"]
        conversation.should_continue = stop_reason == "max_tokens"

        if stop_reason != "tool_use":  # Tool use converged
            message.parent = user_msg_id

            # Retain tool use and its result logs
            tool_logs = [
                log
                for log in thinking_log
                if any(
                    isinstance(content, (ToolUseContentModel, ToolResultContentModel))
                    for content in log.content
                )
            ]
            if tool_logs:
                message.thinking_log = tool_logs

            if chat_input.continue_generate:
                # For continue generate
                if len(thinking_log) == 0:
                    assistant_msg_id = conversation.last_message_id
                    conversation.message_map[assistant_msg_id] = message
                    break

                else:
                    old_assistant_msg_id = conversation.last_message_id
                    conversation.message_map[user_msg_id].children.remove(
                        old_assistant_msg_id
                    )
                    del conversation.message_map[old_assistant_msg_id]

            # Issue id for new assistant message
            assistant_msg_id = str(ULID())
            conversation.message_map[assistant_msg_id] = message

            # Append children to parent
            conversation.message_map[user_msg_id].children.append(assistant_msg_id)
            conversation.last_message_id = assistant_msg_id

            search_results_as_related_documents = [
                search_result_to_related_document(
                    search_result=result,
                    source_id_base=assistant_msg_id,
                )
                for result in search_results
            ]
            related_documents.extend(search_results_as_related_documents)
            break

        tool_use_message = SimpleMessageModel.from_message_model(message=message)
        if continue_generate:
            messages[-1] = tool_use_message

            continue_generate = False
            message_for_continue_generate = None

        else:
            messages.append(tool_use_message)

        thinking_log.append(tool_use_message)

        tool_use_contents = [
            content
            for content in tool_use_message.content
            if isinstance(content, ToolUseContentModel)
        ]

        run_results: list[ToolRunResult] = []
        for content in tool_use_contents:
            tool = tools[content.body.name]
            run_result = tool.run(
                tool_use_id=content.body.tool_use_id,
                input=content.body.input,
                model=chat_input.message.model,
                bot=bot,
            )
            run_results.append(run_result)

            if run_result["status"] == "success":
                related_documents.extend(run_result["related_documents"])

            if on_tool_result:
                on_tool_result(run_result)

        tool_result_message = SimpleMessageModel(
            role="user",
            content=[
                ToolResultContentModel.from_tool_run_result(
                    run_result=result,
                    model=chat_input.message.model,
                    display_citation=display_citation,
                )
                for result in run_results
            ],
        )
        messages.append(tool_result_message)
        thinking_log.append(tool_result_message)

    # Store conversation before finish streaming so that front-end can avoid 404 issue
    store_conversation(user.id, conversation)
    store_related_documents(
        user_id=user.id,
        conversation_id=conversation.id,
        related_documents=related_documents,
    )

    if on_stop:
        on_stop(result)

    # Update bot last used time
    if bot:
        logger.info("Bot is provided. Updating bot last used time.")
        # Update bot last used time
        modify_bot_last_used_time(user, bot)
        # Update bot stats
        modify_bot_stats(user, bot, increment=1)

    return conversation, message


def chat_output_from_message(
    conversation: ConversationModel,
    message: MessageModel,
) -> ChatOutput:
    return ChatOutput(
        conversation_id=conversation.id,
        create_time=conversation.create_time,
        message=MessageOutput(
            role=message.role,
            content=[c.to_content() for c in message.content],
            model=message.model,
            children=message.children,
            parent=message.parent,
            feedback=None,
            used_chunks=(
                [
                    Chunk(
                        content=c.content,
                        content_type=c.content_type,
                        source=c.source,
                        rank=c.rank,
                    )
                    for c in message.used_chunks
                ]
                if message.used_chunks
                else None
            ),
            thinking_log=(
                [m.to_schema() for m in message.thinking_log]
                if message.thinking_log
                else None
            ),
        ),
        bot_id=conversation.bot_id,
    )


def propose_conversation_title(
    user_id: str,
    conversation_id: str,
    model: type_model_name = "claude-v3-haiku",
) -> str:
    PROMPT = """Reading the conversation above, what is the appropriate title for the conversation? When answering the title, please follow the rules below:
<rules>
- Title length must be from 15 to 20 characters.
- Prefer more specific title than general. Your title should always be distinct from others.
- Return the conversation title only. DO NOT include any strings other than the title.
- Title must be in the same language as the conversation.
</rules>
"""
    # Fetch existing conversation
    conversation = find_conversation_by_id(user_id, conversation_id)

    messages = trace_to_root(
        node_id=conversation.last_message_id,
        message_map=conversation.message_map,
    )

    # Append message to generate title
    new_message = SimpleMessageModel(
        role="user",
        content=[
            TextContentModel(
                content_type="text",
                body=PROMPT,
            )
        ],
    )
    messages.append(new_message)

    # Invoke Bedrock
    args = compose_args_for_converse_api(
        messages=[
            message
            for message in messages
            if not any(
                isinstance(content, ToolUseContentModel)
                or isinstance(content, ToolResultContentModel)
                or isinstance(content, ReasoningContentModel)
                for content in message.content
            )
        ],
        model=model,
        stream=False,
    )
    response = call_converse_api(args)
    reply_txt = (
        response["output"]["message"]["content"][0]["text"]
        if "message" in response["output"]
        and len(response["output"]["message"]["content"]) > 0
        and "text" in response["output"]["message"]["content"][0]
        else ""
    )

    return reply_txt


def fetch_conversation(user_id: str, conversation_id: str) -> Conversation:
    conversation = find_conversation_by_id(user_id, conversation_id)

    message_map = {
        message_id: MessageOutput(
            role=message.role,
            content=[c.to_content() for c in message.content],
            model=message.model,
            children=message.children,
            parent=message.parent,
            feedback=(
                FeedbackOutput(
                    thumbs_up=message.feedback.thumbs_up,
                    category=message.feedback.category,
                    comment=message.feedback.comment,
                )
                if message.feedback
                else None
            ),
            used_chunks=(
                [
                    Chunk(
                        content=c.content,
                        content_type=c.content_type,
                        source=c.source,
                        rank=c.rank,
                    )
                    for c in message.used_chunks
                ]
                if message.used_chunks
                else None
            ),
            thinking_log=(
                [m.to_schema() for m in message.thinking_log]
                if message.thinking_log
                else None
            ),
        )
        for message_id, message in conversation.message_map.items()
    }
    # Omit instruction
    if "instruction" in message_map:
        for c in message_map["instruction"].children:
            message_map[c].parent = "system"
        message_map["system"].children = message_map["instruction"].children

        del message_map["instruction"]

    output = Conversation(
        id=conversation_id,
        title=conversation.title,
        create_time=conversation.create_time,
        last_message_id=conversation.last_message_id,
        message_map=message_map,
        bot_id=conversation.bot_id,
        should_continue=conversation.should_continue,
    )
    return output


def search_conversations(query: str, user: User) -> list[ConversationSearchResult]:
    """Search conversations by keyword"""
    conversations = find_conversations_by_query(query, user)
    output = []

    for conversation in conversations:
        # Convert model SearchHighlightModel to schema SearchHighlight
        schema_highlights = None
        if conversation.highlights:
            schema_highlights = [
                SearchHighlight(
                    field_name=highlight.field_name, fragments=highlight.fragments
                )
                for highlight in conversation.highlights
            ]

        # Create ConversationSearchResult with properly converted highlights
        output.append(
            ConversationSearchResult(
                id=conversation.id,
                title=conversation.title,
                last_updated_time=conversation.last_updated_time,
                bot_id=conversation.bot_id,
                highlights=schema_highlights,
            )
        )

    return output
