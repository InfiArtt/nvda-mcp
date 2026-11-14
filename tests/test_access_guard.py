from nvda_mcp.access_guard import private_details

HOME = r"C:\Users\rafli"
TEMP = r"C:\Users\rafli\AppData\Local\Temp"


def check(text, user_name="rafli"):
    return private_details(text, folders=[HOME, TEMP], user_name=user_name)


def test_paths_from_the_helpers_computer_are_found_in_any_spelling():
    assert check(r"Buka C:\Users\Rafli\Documents\rahasia.txt") == "a folder path from this computer"
    assert check("see c:/users/rafli/.ssh/id_ed25519") == "a folder path from this computer"
    assert check(r"D:\home\rafli\notes") == "a path with this computer's user name"


def test_secrets_with_a_known_shape_are_found():
    assert check("-----BEGIN OPENSSH PRIVATE KEY-----") == "a private key"
    assert check("token ghp_" + "a1B2" * 9) == "a GitHub token"
    assert check("sk-" + "x" * 30) == "an API key"
    assert check("AKIAABCDEFGHIJKLMNOP") == "an AWS key"


def test_ordinary_help_passes():
    assert check(r"Buka C:\Users\Alfian\Documents\lomba.txt di Notepad") is None
    assert check("Tanggal 14/10/2026, tekan Ctrl+S untuk menyimpan.", user_name="10") is None
    assert check("Rafli akan membantu Kakak.") is None
