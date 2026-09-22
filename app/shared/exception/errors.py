class BusinessException(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ResourceNotFoundException(Exception):
    def __init__(self, resource_name: str, field_name: str, field_value: object):
        message = f"{resource_name} not found with {field_name}: '{field_value}'"
        super().__init__(message)
        self.message = message


class DuplicateResourceException(Exception):
    def __init__(self, resource_name: str, field_name: str, field_value: object):
        message = f"{resource_name} already exists with {field_name}: '{field_value}'"
        super().__init__(message)
        self.message = message


class PermissionDeniedException(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AuthenticationRequiredException(Exception):
    pass
