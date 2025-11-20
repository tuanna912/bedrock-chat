import { createMachine, assign } from 'xstate';
import { produce } from 'immer';

import { AgentToolsProps, AgentToolState } from '../../features/agent/types';
import { RelatedDocument } from '../../@types/conversation';

export const StreamingState = {
  SLEEPING: 'sleeping',
  STREAMING: 'streaming',
  LEAVING: 'leaving',
} as const;

export type StreamingState = (typeof StreamingState)[keyof typeof StreamingState];

export type StreamingContext = {
  /** ReasoningContent in assistant message itself. */
  reasoning: string;
  /** TextContent in assistant message itself. */
  text: string;
  tools: AgentToolsProps[];
  relatedDocuments: RelatedDocument[];
};

export type StreamingEvent =
  | { type: 'wakeup' }
  | {
      type: 'reasoning';
      reasoning: string;
    }
  | {
      type: 'text';
      text: string;
    }
  | {
      type: 'tool-use';
      toolUseId: string;
      name: string;
      input: { [key: string]: any }; // eslint-disable-line @typescript-eslint/no-explicit-any
    }
  | {
      type: 'tool-result';
      toolUseId: string;
      status: AgentToolState;
    }
  | {
      type: 'related-document';
      toolUseId: string;
      relatedDocument: RelatedDocument;
    }
  | { type: 'reset' }
  | { type: 'goodbye' };

export const streamingStateMachine = createMachine<StreamingContext, StreamingEvent>({
  id: 'streaming',
  context: {
    reasoning: '',
    text: '',
    tools: [],
    relatedDocuments: [],
  },
  initial: 'sleeping',
  states: {
    sleeping: {
      on: {
        wakeup: {
          actions: assign({
            reasoning: '',
            text: '',
            tools: [],
            relatedDocuments: [],
          }),
          target: 'streaming',
        },
      },
    },
    streaming: {
      on: {
        reasoning: {
          actions: assign({
            reasoning: (context, event) =>
              event.type === 'reasoning'
                ? context.reasoning + event.reasoning
                : context.reasoning,
          }),
        },
        text: {
          actions: assign({
            text: (context, event) =>
              event.type === 'text'
                ? context.text + event.text
                : context.text,
          }),
        },
        'tool-use': {
          actions: assign((context, event) => {
            return produce(context, (draft: StreamingContext) => {
              if (event.type === 'tool-use') {
                const reasoning = draft.reasoning ? draft.reasoning : undefined;
                draft.reasoning = '';

                const text = draft.text ? draft.text : undefined;
                draft.text = '';

                if (draft.tools.length > 0 && text == null && reasoning == null) {
                  draft.tools[draft.tools.length - 1].tools[event.toolUseId] = {
                    name: event.name,
                    input: event.input,
                    status: 'running',
                  };
                } else {
                  draft.tools.push({
                    reasoning: reasoning,
                    thought: text,
                    tools: {
                      [event.toolUseId]: {
                        name: event.name,
                        input: event.input,
                        status: 'running',
                      },
                    },
                  });
                }
              }
            });
          }),
        },
        'tool-result': {
          actions: assign({
            tools: (context, event) => {
              return produce(context.tools, (draft: AgentToolsProps[]) => {
                if (event.type === 'tool-result') {
                  const tool = draft.find(tool => event.toolUseId in tool.tools);
                  if (tool != null) {
                    tool.tools[event.toolUseId].status = event.status;
                  }
                }
              });
            },
          }),
        },
        'related-document': {
          actions: assign((context, event) => {
            return produce(context, (draft: StreamingContext) => {
              if (event.type === 'related-document') {
                const tool = draft.tools.find(tool => event.toolUseId in tool.tools);
                if (tool != null) {
                  const toolUse = tool.tools[event.toolUseId];
                  if (toolUse.relatedDocuments == null) {
                    toolUse.relatedDocuments = [event.relatedDocument];
                  } else {
                    toolUse.relatedDocuments.push(event.relatedDocument);
                  }
                }
                draft.relatedDocuments.push(event.relatedDocument);
              }
            });
          }),
        },
        reset: {
          actions: assign({
            reasoning: '',
            text: '',
            tools: [],
            relatedDocuments: [],
          }),
        },
        goodbye: {
          target: 'leaving',
        },
      },
    },
    leaving: {
      after: {
        2500: { target: 'sleeping' },
      },
    },
  },
});
