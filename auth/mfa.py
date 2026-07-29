import pyotp

MFA_ISSUER_NAME = "MobilityFlow AI"


def generate_mfa_secret():
    return pyotp.random_base32()


def get_provisioning_uri(secret, username):
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=MFA_ISSUER_NAME)


def verify_totp_code(secret, code):
    if not secret or not code:
        return False
    totp = pyotp.TOTP(secret)
    # valid_window=1 tolerates the code from one 30s step before/after,
    # to absorb minor clock drift between server and the user's phone.
    return totp.verify(code, valid_window=1)
