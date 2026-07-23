## Environment Setup

**Backend**:

```bash
poetry init
poetry add fastapi uvicorn websockets asyncpg sqlalchemy
poetry install
```

**Frontend**:

```bash
npx create-react-app chat-frontend
cd chat-frontend
npm install socket.io-client
```

**Database**:

- PostgreSQL running locally
- Create database + run migration scripts

