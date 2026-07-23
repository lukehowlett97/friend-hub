#!/usr/bin/env python3
"""
Simple test tool for Friend Hub Chat
Tests WebSocket connection and basic messaging
"""
import asyncio
import websockets
import json
import requests
import subprocess

async def test_basic_connection():
    """Test 1: Can we connect to WebSocket?"""
    print("🔍 Test 1: Basic WebSocket connection")
    
    # First, create a session via REST API
    session_response = requests.post('http://localhost:8000/api/v1/session', 
                                   json={'nickname': 'TestBot'})
    
    if session_response.status_code != 200:
        print("❌ Failed to create session")
        return False
        
    session_data = session_response.json()
    session_id = session_data['session_id']
    print(f"✅ Created session: {session_id}")
    
    return True

async def test_websocket_connection(session_id):
    """Test 2: Can we connect via WebSocket?"""
    print("🔍 Test 2: WebSocket connection")
    
    try:
        uri = f"ws://localhost:8000/ws/{session_id}"
        async with websockets.connect(uri) as websocket:
            print("✅ WebSocket connected")
            
            # Wait for connection message
            message = await websocket.recv()
            data = json.loads(message)
            print(f"📨 Received: {data['type']}")
            
            return True
            
    except Exception as e:
        print(f"❌ WebSocket failed: {e}")
        return False
    
async def test_send_message(session_id):
    """Test 3: Can we send and receive a message?"""
    print("🔍 Test 3: Message sending")
    
    try:
        uri = f"ws://localhost:8000/ws/{session_id}"
        async with websockets.connect(uri) as websocket:
            # Skip connection message
            await websocket.recv()
            
            # Set nickname first
            nickname_msg = {"type": "set_nickname", "nickname": "TestBot3"}
            await websocket.send(json.dumps(nickname_msg))
            
            # Wait for nickname confirmation
            await websocket.recv()
            print("✅ Nickname set")
            
            # Send test message
            test_msg = {"type": "message", "content": "Hello from test bot!"}
            await websocket.send(json.dumps(test_msg))
            print("📤 Test message sent")
            
            # Wait briefly for message to be processed
            await asyncio.sleep(0.5)
            print("✅ Message test complete")
            
            return True
            
    except Exception as e:
        print(f"❌ Message test failed: {e}")
        return False
    
def test_message_in_database():
    """Test 4: Verify message was saved to database"""
    print("🔍 Test 4: Database verification")
    
    try:
        # Query the database for our test message
        cmd = [
            'psql', 
            'postgresql://chatuser:chatpass@localhost:5432/chatapp',
            '-c', 
            "SELECT content FROM messages WHERE content = 'Hello from test bot!' ORDER BY created_at DESC LIMIT 1;"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0 and "Hello from test bot!" in result.stdout:
            print("✅ Message found in database")
            return True
        else:
            print("❌ Message not found in database")
            print(f"Database output: {result.stdout}")
            return False
            
    except Exception as e:
        print(f"❌ Database check failed: {e}")
        return False

if __name__ == "__main__":
    async def run_tests():
        # Test 1: Session creation
        success = await test_basic_connection()
        if not success:
            return
            
        # Get session ID for WebSocket test
        session_response = requests.post('http://localhost:8000/api/v1/session', 
                                       json={'nickname': 'TestBot2'})
        session_id = session_response.json()['session_id']
        
        # Test 2: WebSocket connection
        session_response = requests.post('http://localhost:8000/api/v1/session', 
                                       json={'nickname': 'TestBot2'})
        session_id = session_response.json()['session_id']
        success = await test_websocket_connection(session_id)
        if not success:
            return
        
        # Test 3: Message sending
        session_response = requests.post('http://localhost:8000/api/v1/session', 
                                       json={'nickname': 'TestBot3'})
        session_id = session_response.json()['session_id']
        await test_send_message(session_id)
        
        # Give database time to save
        await asyncio.sleep(1)
        
        # Test 4: Database verification
        test_message_in_database()
    
    asyncio.run(run_tests())