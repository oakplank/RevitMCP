import requests
import json

# Test the chat API with the new sheet placement tool
def test_sheet_placement():
    url = "http://localhost:8000/chat_api"
    
    # First test: List available views
    payload_list = {
        "conversation": [
            {
                "role": "user",
                "content": "List all available views that can be placed on sheets"
            }
        ],
        "apiKey": "test-key",
        "model": "claude-4-sonnet"
    }
    
    # Second test: Place a view on sheet
    payload_place = {
        "conversation": [
            {
                "role": "user",
                "content": "Place level 3 mezz floor plan on a sheet"
            }
        ],
        "apiKey": "test-key", 
        "model": "claude-4-sonnet"
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    print("=== Testing List Views Tool ===")
    try:
        response = requests.post(url, json=payload_list, headers=headers)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            reply = result.get('reply', 'No reply found')
            print(f"Reply: {reply[:500]}...")  # First 500 chars
            
            # Check if the response mentions the tools
            if "list_views" in reply.lower() or "place_view" in reply.lower():
                print("✅ Sheet tools are recognized!")
            else:
                print("❌ Sheet tools may not be recognized")
        else:
            print(f"Error response: {response.text}")
        
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n=== Testing Place View Tool ===")
    try:
        response = requests.post(url, json=payload_place, headers=headers)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            reply = result.get('reply', 'No reply found')
            print(f"Reply: {reply[:500]}...")  # First 500 chars
            
            # Check if the response mentions the tools
            if "place_view" in reply.lower() or "sheet" in reply.lower():
                print("✅ Sheet placement tool is working!")
            else:
                print("❌ Sheet placement tool may not be working")
        else:
            print(f"Error response: {response.text}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_sheet_placement() 