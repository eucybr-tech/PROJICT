import getpass
import sqlite3
import sys

from database import Database
from services.account_manager import AccountManager


def main() -> int:
    database = Database()
    try:
        database.initialize_schema()
        username = input("Admin username: ").strip()
        new_password = getpass.getpass("New password: ")
        confirmation = getpass.getpass("Confirm new password: ")
        AccountManager(database).recover_admin_password(
            username, new_password, confirmation
        )
    except (ValueError, TypeError, sqlite3.Error) as error:
        print(f"Password recovery failed: {error}", file=sys.stderr)
        return 1
    finally:
        database.close()
    print("Admin password updated. Existing data was not deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
