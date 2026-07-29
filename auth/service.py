from db.database import get_user, log_security_event
from auth.password import verify_password


def authenticate_user(username, password):

    username = username.strip()
    password = password.strip()

    user = get_user(username)

    if user is None:

        log_security_event(
            username,
            "LOGIN",
            "Invalid credentials",
            success=False
        )

        return None


    if verify_password(
        password,
        user["password"]
    ):

        log_security_event(
            username,
            "LOGIN",
            "Login successful",
            success=True
        )

        return user


    log_security_event(
        username,
        "LOGIN",
        "Invalid credentials",
        success=False
    )

    return None