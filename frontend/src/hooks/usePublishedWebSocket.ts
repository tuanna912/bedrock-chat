import { PostMessageRequest } from '../@types/conversation';
import { create } from 'zustand';
import i18next from 'i18next';
import { StreamingEvent } from './xstates/streaming';
import { PostStreamingStatus } from '../constants';

const CHUNK_SIZE = 32 * 1024; //32KB

const usePublishedWebSocket = create<{
  post: (params: {
    wsEndpoint: string;
    apiKey: string;
    input: Omit<PostMessageRequest, 'botId'>;
    handleStreamingEvent: (event: StreamingEvent) => void;
  }) => Promise<void>;
  errorDetail: string | null;
}>((set) => {
  return {
    errorDetail: null,
    post: async ({ wsEndpoint, apiKey, input, handleStreamingEvent }) => {
      handleStreamingEvent({ type: 'wakeup' });

      const payloadString = JSON.stringify({
        ...input,
        apiKey, // Send API key instead of token
      });

      // Chunking
      const chunkedPayloads: string[] = [];
      const chunkCount = Math.ceil(payloadString.length / CHUNK_SIZE);
      for (let i = 0; i < chunkCount; i++) {
        const start = i * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE, payloadString.length);
        chunkedPayloads.push(payloadString.substring(start, end));
      }

      let receivedCount = 0;
      return new Promise<void>((resolve, reject) => {
        const ws = new WebSocket(wsEndpoint);

        ws.onopen = () => {
          console.log('[PUBLISHED_WS] WebSocket connection opened');
          ws.send(
            JSON.stringify({
              step: PostStreamingStatus.START,
              apiKey: apiKey,
            })
          );
        };

        ws.onmessage = (message) => {
          try {
            if (
              message.data === '' ||
              message.data === 'Message sent.' ||
              message.data.startsWith(
                '{"message": "Endpoint request timed out",'
              )
            ) {
              return;
            } else if (message.data === 'Session started.') {
              chunkedPayloads.forEach((chunk, index) => {
                ws.send(
                  JSON.stringify({
                    step: PostStreamingStatus.BODY,
                    index,
                    part: chunk,
                  })
                );
              });
              return;
            } else if (message.data === 'Message part received.') {
              receivedCount++;
              if (receivedCount === chunkedPayloads.length) {
                ws.send(
                  JSON.stringify({
                    step: PostStreamingStatus.END,
                    apiKey: apiKey,
                  })
                );
              }
              return;
            }

            const data = JSON.parse(message.data);

            if (data.status) {
              switch (data.status) {
                case PostStreamingStatus.AGENT_THINKING: {
                  Object.entries(data.log).forEach(([toolUseId, toolInfo]) => {
                    const typedToolInfo = toolInfo as {
                      name: string;
                      input: { [key: string]: any };
                    };
                    handleStreamingEvent({
                      type: 'tool-use',
                      toolUseId: toolUseId,
                      name: typedToolInfo.name,
                      input: typedToolInfo.input,
                    });
                  });
                  break;
                }
                case PostStreamingStatus.AGENT_TOOL_RESULT:
                  handleStreamingEvent({
                    type: 'tool-result',
                    toolUseId: data.result.toolUseId,
                    status: data.result.status,
                  });
                  break;
                case PostStreamingStatus.REASONING:
                  handleStreamingEvent({
                    type: 'reasoning',
                    reasoning: data.completion,
                  });
                  break;
                case PostStreamingStatus.STREAMING:
                  handleStreamingEvent({
                    type: 'text',
                    text: data.completion,
                  });
                  break;
                case PostStreamingStatus.STREAMING_END:
                  handleStreamingEvent({
                    type: 'goodbye',
                  });
                  ws.close();
                  break;
                case PostStreamingStatus.ERROR:
                  ws.close();
                  set({
                    errorDetail:
                      data.reason || i18next.t('error.predict.invalidResponse'),
                  });
                  throw new Error(
                    data.reason || i18next.t('error.predict.invalidResponse')
                  );
                default:
                  handleStreamingEvent({
                    type: 'reset',
                  });
                  break;
              }
            } else {
              ws.close();
              throw new Error(i18next.t('error.predict.invalidResponse'));
            }
          } catch (e) {
            console.error('[PUBLISHED_WS] Error:', e);
            reject(i18next.t('error.predict.general'));
          }
        };

        ws.onerror = (e) => {
          console.error('[PUBLISHED_WS] WebSocket error:', e);
          ws.close();
          reject(i18next.t('error.predict.general'));
        };
        ws.onclose = () => {
          resolve();
        };
      });
    },
  };
});

export default usePublishedWebSocket;
