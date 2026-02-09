from langchain.memory import ConversationBufferMemory


class Memory:
    """
    Drop-in replacement for mem0.Memory
    Wraps LangChain ConversationBufferMemory
    """

    def __init__(self, memory_key: str = "chat_history"):
        self._memory = ConversationBufferMemory(
            memory_key=memory_key,
            return_messages=True
        )

    def load(self):
        """
        Equivalent to mem0 memory fetch
        """
        return self._memory.load_memory_variables({}).get("chat_history", [])

    def save(self, user_input: str, assistant_output: str):
        """
        Equivalent to mem0 memory write
        """
        self._memory.save_context(
            {"input": user_input},
            {"output": assistant_output}
        )

    def clear(self):
        self._memory.clear()


class MemoryClient:
    """
    Drop-in replacement for mem0.MemoryClient
    """

    def __init__(self, *args, **kwargs):
        # args kept for compatibility
        self.memory = Memory()

    def get_memory(self, *args, **kwargs) -> Memory:
        return self.memory
