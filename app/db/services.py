from app.db.repositories import MessageRepo, SessionRepo, TopicRepo, UserRepo


class ChatDBService:
    def __init__(self, db):
        self.db = db
        self.users = UserRepo(db)
        self.topics = TopicRepo(db)
        self.sessions = SessionRepo(db)
        self.messages = MessageRepo(db)

    def ensure_user(self, telegram_user_id: int, display_name: str | None):
        return self.users.get_or_create(telegram_user_id=telegram_user_id, display_name=display_name)

    def get_topic_for_chat_thread(self, chat_id: int, thread_id: int | None, user_id=None):
        return self.topics.get_by_chat_thread(chat_id, thread_id, user_id=user_id)

    def get_or_create_active_session(self, user_id, topic_id, mode: str = "practical"):
        return self.sessions.get_or_create_active(user_id=user_id, topic_id=topic_id, mode=mode)

    def save_user_message(self, session_id, content: str, telegram_message_id: int | None = None):
        return self.messages.add(
            session_id=session_id,
            role="user",
            content=content,
            telegram_message_id=telegram_message_id,
        )

    def save_assistant_message(self, session_id, content: str, metadata: dict | None = None):
        return self.messages.add(
            session_id=session_id,
            role="assistant",
            content=content,
            metadata=metadata or {},
        )
