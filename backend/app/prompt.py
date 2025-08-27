from app.bedrock import is_nova_model
from app.vector_search import SearchResult
from app.routes.schemas.conversation import type_model_name


def build_rag_prompt(
    search_results: list[SearchResult],
    model: type_model_name,
    display_citation: bool = True,
) -> str:
    # Handle case where no high-quality search results are available
    if not search_results:
        return """CRITICAL INSTRUCTIONS: No relevant information was found in the knowledge base for this query.

You MUST respond with: "Tôi không tìm thấy thông tin về vấn đề này trong cơ sở dữ liệu hiện có. Vui lòng kiểm tra lại câu hỏi hoặc liên hệ với bộ phận hỗ trợ để được giúp đỡ thêm."

DO NOT attempt to answer from general knowledge or make assumptions.
"""
    
    context_prompt = ""
    for result in search_results:
        context_prompt += f"<search_result>\n<content>\n{result['content']}</content>\n<source>\n{result['rank']}\n</source>\n</search_result>"

    # Enhanced prompt for RAG with strict knowledge base adherence
    inserted_prompt = """CRITICAL INSTRUCTIONS: You are a knowledge base assistant that MUST ONLY use information from the provided search results.

STRICT RULES:
1. ONLY answer using information explicitly found in the search results below
2. If the search results do not contain sufficient information to answer the question, you MUST respond: "Tôi không tìm thấy thông tin về vấn đề này trong cơ sở dữ liệu hiện có."
3. DO NOT use your general knowledge or training data
4. DO NOT make assumptions or inferences beyond what is explicitly stated
5. DO NOT create or invent any information not present in the search results
6. If you're uncertain whether the information is in the search results, err on the side of saying you don't know

VALIDATION CHECKLIST before answering:
- Is this information explicitly stated in the search results? 
- Am I using only the provided knowledge base content?
- Am I avoiding any external knowledge or assumptions?

Here are the search results from the knowledge base:
<search_results>
{}
</search_results>

Answer the user's question concisely using ONLY the information above. If insufficient information is available, clearly state that you cannot answer based on the available knowledge base.
""".format(
        context_prompt,
    )

    if display_citation:
        # Prompt for 'Retrieved Context Citation'.
        inserted_prompt += """
If you reference information from a search result within your answer, you must include a citation to source where the information was found.
Each result has a corresponding source ID that you should reference.

Note that <sources> may contain multiple <source> if you include information from multiple results in your answer.
Do NOT outputs sources at the end of your answer.

Followings are examples of how to reference sources in your answer. Note that the source ID is embedded in the answer in the format [^<source_id>].
"""
        # Prompt to output Markdown-style citation.
        if is_nova_model(model=model):
            # For Amazon Nova, provides only good examples.
            inserted_prompt += """
<example>
first answer [^3]. second answer [^1][^2].
</example>

<example>
first answer [^1][^5]. second answer [^2][^3][^4]. third answer [^4].
</example>
"""

        else:
            # For other models, provide good examples and bad examples.
            inserted_prompt += """
<GOOD-example>
first answer [^3]. second answer [^1][^2].
</GOOD-example>

<GOOD-example>
first answer [^1][^5]. second answer [^2][^3][^4]. third answer [^4].
</GOOD-example>

<BAD-example>
first answer [^1].

[^1]: https://example.com
</BAD-example>

<BAD-example>
first answer [^1].

<sources>
[^1]: https://example.com
</sources>
</BAD-example>
"""

    else:
        # Prompt when 'Retrieved Context Citation' is not specified.
        inserted_prompt += """
Do NOT include citations in the format [^<source_id>] in your answer.
"""
        if is_nova_model(model=model):
            # For Amazon Nova, do not provide examples.
            pass

        else:
            # For other models, suppress output of Markdown-style citation.
            inserted_prompt += """
Followings are examples of how to answer.

<GOOD-example>
first answer. second answer.
</GOOD-example>

<BAD-example>
first answer [^3]. second answer [^1][^2].
</BAD-example>

<BAD-example>
first answer [^1][^5]. second answer [^2][^3][^4]. third answer [^4].
</BAD-example>
"""

    return inserted_prompt


def get_prompt_to_cite_tool_results(model: type_model_name) -> str:
    # Enhanced prompt for tool-based RAG with strict knowledge base adherence
    inserted_prompt = """CRITICAL INSTRUCTIONS: You are a knowledge base assistant that MUST ONLY use information from the provided tool results.

STRICT RULES:
1. ONLY answer using information explicitly found in the tool results below
2. If the tool results do not contain sufficient information to answer the question, you MUST respond: "Tôi không tìm thấy thông tin về vấn đề này trong cơ sở dữ liệu hiện có."
3. DO NOT use your general knowledge or training data
4. DO NOT make assumptions or inferences beyond what is explicitly stated in tool results
5. DO NOT create or invent any information not present in the tool results
6. If you're uncertain whether the information is in the tool results, err on the side of saying you don't know

VALIDATION CHECKLIST before answering:
- Is this information explicitly stated in the tool results?
- Am I using only the provided knowledge base content?
- Am I avoiding any external knowledge or assumptions?

Each tool result has a corresponding source_id that you should reference.
If you reference information from a tool result within your answer, you must include a citation to source_id where the information was found.

Followings are examples of how to reference source_id in your answer. Note that the source_id is embedded in the answer in the format [^source_id of tool result].
"""
    # Prompt to output Markdown-style citation.
    if is_nova_model(model=model):
        # For Amazon Nova, provides only good examples.
        inserted_prompt += """
<example>
first answer [^ccc]. second answer [^aaa][^bbb].
</example>

<example>
first answer [^aaa][^eee]. second answer [^bbb][^ccc][^ddd]. third answer [^ddd].
</example>
"""

    else:
        # For other models, provide good examples and bad examples.
        inserted_prompt += """
<examples>
<GOOD-example>
first answer [^ccc]. second answer [^aaa][^bbb].
</GOOD-example>

<GOOD-example>
first answer [^aaa][^eee]. second answer [^bbb][^ccc][^ddd]. third answer [^ddd].
</GOOD-example>

<BAD-example>
first answer [^aaa].

[^aaa]: https://example.com
</BAD-example>

<BAD-example>
first answer [^aaa].

<sources>
[^aaa]: https://example.com
</sources>
</BAD-example>
</examples>
"""

    return inserted_prompt
