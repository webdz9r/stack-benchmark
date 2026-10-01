class AppError(Exception):
    """An error with an HTTP status; rendered as {"error": message}."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message

    @classmethod
    def not_found(cls) -> "AppError":
        return cls(404, "not found")

    @classmethod
    def validation(cls, message: str) -> "AppError":
        return cls(422, message)

    @classmethod
    def conflict(cls, message: str) -> "AppError":
        return cls(409, message)
