from app.auth.hashing import hash_password, hash_token, verify_password


def test_hash_password_generates_valid_hash():

    raw_password = "password"
    hashed = hash_password(raw_password)

    assert hashed != raw_password

    assert len(hashed) > 0
    assert hashed.startswith("$argon2")


def test_verify_password_correct():

    raw_password = "Password123!"
    hashed = hash_password(raw_password)

    is_valid = verify_password(raw_password, hashed)
    assert is_valid is True


def test_verify_password_incorrect():

    raw_password = "correctPassword"
    wrong_password = "wrongPassword"
    hashed = hash_password(raw_password)

    is_valid = verify_password(wrong_password, hashed)
    assert is_valid is False


def test_hash_token_is_deterministic():

    token = "random-uuid-or-secret-token-1234"
    hash_1 = hash_token(token)
    hash_2 = hash_token(token)

    assert len(hash_1) == 64

    assert hash_1 == hash_2
