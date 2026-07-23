# Backend Architecture

## Overview

Clean, domain-driven architecture for the Friend Hub Chat backend. Replaces monolithic services with focused, testable components.

## Directory Structure

```
backend/app/
├── main.py                 # FastAPI app setup & startup/shutdown
├── config.py              # Application configuration
├── models/                 # SQLAlchemy database models
├── domains/                # Business domains (core logic)
├── api/                    # HTTP & WebSocket endpoints
└── services/               # Legacy/orchestrator services
```

## 🏗️ Domains (`domains/`)

### `chat/` - Real-time Communication
- **`connection_manager.py`** - Manages WebSocket connections & broadcasting
- **`message_handler.py`** - Routes WebSocket messages to appropriate handlers
- **`events.py`** - Type-safe WebSocket event schemas (Pydantic models)

### `users/` - User Management  
- **`repository.py`** - User data access layer (CRUD operations)
- **`service.py`** - User business logic (validation, nickname rules)

### `messages/` - Message Handling
- **`repository.py`** - Message data access layer (save, retrieve, delete)
- **`service.py`** - Message business logic (content validation, formatting)

## 🌐 API (`api/`)

### `v1/` - Version 1 Endpoints
- **`router.py`** - REST API endpoints (`/health`, `/session`, `/messages`)
- **`websocket.py`** - Clean WebSocket endpoint handler

## 🔧 Services (`services/`)

- **`chat_service.py`** - Lightweight orchestrator that delegates to domain services

## 🎯 Architecture Benefits

### Separation of Concerns
- **Repositories**: Only handle database operations
- **Services**: Only handle business logic  
- **API**: Only handle HTTP/WebSocket protocol
- **Events**: Type-safe message contracts

### Easy Testing
```python
# Test business logic in isolation
user_service = UserService(mock_db)
user, error = await user_service.create_or_update_user("123", "Alice")

# Test data access in isolation  
message_repo = MessageRepository(mock_db)
message = await message_repo.create_message("123", "Hello!")
```

### Easy Extension
Adding new features (reactions, file uploads) requires:
1. Create new domain (`domains/reactions/`)
2. Add repository & service
3. Add handler to `message_handler.py`
4. No changes to existing code!

## 🔄 Request Flow

### WebSocket Message:
```
Client → websocket.py → message_handler.py → domain services → database
                     ← connection_manager.py ← broadcast response ←
```

### REST API:
```
Client → router.py → domain services → database
                  ← JSON response ←
```

## 🚀 Key Improvements

| Before | After |
|--------|-------|
| 300+ line `main.py` | 60 line focused setup |
| Giant `ChatService` | Clean domain separation |
| Mixed responsibilities | Single responsibility per class |
| Hard to test | Easy unit testing |
| Hard to extend | Trivial to add features |

## 📋 Adding New Features

### Example: Adding Reactions
1. **Create domain**: `domains/reactions/repository.py` & `service.py`
2. **Add event**: New reaction events in `events.py`
3. **Add handler**: `message_handler.py` gets new `_handle_reaction()`
4. **Add endpoint**: `router.py` gets `/reactions` if needed

Existing code remains untouched!

## 🧪 Testing Strategy

- **Unit tests**: Test each service/repository in isolation
- **Integration tests**: Test API endpoints end-to-end
- **WebSocket tests**: Test message routing & broadcasting

## 📚 Dependencies

- **FastAPI**: Web framework
- **SQLAlchemy**: Database ORM  
- **Pydantic**: Data validation & serialization
- **WebSockets**: Real-time communication