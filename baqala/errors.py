"""استثناءات النظام. الرسالة دائماً بالعربية لعرضها للمستخدم مباشرة."""


class POSError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ValidationError(POSError):
    pass


class NotFoundError(POSError):
    pass


class PermissionDenied(POSError):
    pass


class InsufficientStock(POSError):
    pass


class CreditLimitExceeded(POSError):
    pass


class AuthError(POSError):
    pass
