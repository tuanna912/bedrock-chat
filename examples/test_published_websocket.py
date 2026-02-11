#!/usr/bin/env python3
"""Test script for Published WebSocket API"""

import asyncio
import json
import websockets

# Configuration
WS_ENDPOINT = "wss://your-api-id.execute-api.us-east-1.amazonaws.com/prod"
API_KEY = "tvZvFpHxVb5WqLUOPfEOd63rWNRanRgF612GwafS"
CHUNK_SIZE = 32 * 1024


async def test_chat(message: str):
    """Send a chat message and receive streaming response"""
    
    # Prepare payload
    payload = json.dumps({
        "conversationId": None,
        "message": {
            "role": "user",
            "content": [{"contentType": "text", "body": message}],
            "model": "claude-v3.7-sonnet",
            "parentMessageId": None
        },
        "enableReasoning": False
    })
    
    # Chunk payload
    chunks = []
    for i in range(0, len(payload), CHUNK_SIZE):
        chunks.append(payload[i:i + CHUNK_SIZE])
    
    print(f"📤 Sending message: {message}")
    print(f"📦 Payload size: {len(payload)} bytes, {len(chunks)} chunks\n")
    
    async with websockets.connect(WS_ENDPOINT) as ws:
        # Step 1: START
        await ws.send(json.dumps({
            "step": "START",
            "apiKey": API_KEY
        }))
        
        response = await ws.recv()
        print(f"✅ {response}")
        
        if response != "Session started.":
            print(f"❌ Unexpected response: {response}")
            return
        
        # Step 2: Send chunks
        for index, chunk in enumerate(chunks):
            await ws.send(json.dumps({
                "step": "BODY",
                "index": index,
                "part": chunk
            }))
            response = await ws.recv()
            print(f"✅ Chunk {index + 1}/{len(chunks)} received")
        
        # Step 3: END
        await ws.send(json.dumps({
            "step": "END",
            "apiKey": API_KEY
        }))
        
        print("\n🤖 Assistant response:\n")
        
        # Receive streaming response
        full_response = ""
        while True:
            try:
                data = await ws.recv()
                
                if data in ["Message sent.", ""]:
                    continue
                
                parsed = json.loads(data)
                
                if parsed.get("status") == "STREAMING":
                    token = parsed.get("completion", "")
                    print(token, end="", flush=True)
                    full_response += token
                    
                elif parsed.get("status") == "STREAMING_END":
                    print("\n\n✅ Streaming completed")
                    print(f"📊 Token count: {parsed.get('token_count')}")
                    print(f"💰 Price: ${parsed.get('price', 0):.6f}")
                    break
                    
                elif parsed.get("status") == "ERROR":
                    print(f"\n❌ Error: {parsed.get('reason')}")
                    break
                    
            except websockets.exceptions.ConnectionClosed:
                break
        
        return full_response


async def main():
    """Run test cases"""
    
    print("=" * 60)
    print("🧪 Testing Published WebSocket API")
    print("=" * 60)
    print(f"Endpoint: {WS_ENDPOINT}")
    print(f"API Key: {API_KEY[:20]}...")
    print("=" * 60 + "\n")
    
    # Test case 1
    await test_chat("Hello! What is AWS Bedrock?")
    
    print("\n" + "=" * 60 + "\n")
    
    # Test case 2
    await test_chat("Explain Lambda in 2 sentences")


if __name__ == "__main__":
    asyncio.run(main())
