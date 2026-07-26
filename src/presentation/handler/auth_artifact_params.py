AUTH_EXCHANGE_TOKEN_FIELD_NAME = "auth_exchange_token"
LEGACY_AUTH_EXCHANGE_TOKEN_FIELD_NAME = "token"


def read_auth_exchange_token(body: dict | None) -> str | None:
    if not body:
        return None

    auth_exchange_token = body.get(AUTH_EXCHANGE_TOKEN_FIELD_NAME)
    if auth_exchange_token:
        return auth_exchange_token

    return body.get(LEGACY_AUTH_EXCHANGE_TOKEN_FIELD_NAME)
