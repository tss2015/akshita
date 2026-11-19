"""Write Fernet-encrypted sessions from a hidden terminal prompt; never overwrite a file."""
import getpass
import os
import sys
from cryptography.fernet import Fernet

if len(sys.argv) != 2:
    raise SystemExit('Usage: python scripts/encrypt_sessions.py /path/to/new-file')
key = os.environ.get('ASSISTANT_KEY')
if not key:
    raise SystemExit('Set ASSISTANT_KEY in your environment first.')
sessions = getpass.getpass('Assistant session strings (comma-separated): ').strip()
if not sessions:
    raise SystemExit('No sessions supplied.')
data = Fernet(key.encode()).encrypt(sessions.encode())
fd = os.open(sys.argv[1], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
with os.fdopen(fd, 'wb') as output:
    output.write(data)
print('Encrypted session file created.')
