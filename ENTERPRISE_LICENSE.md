# NexTerm Enterprise License

Enterprise activation is validated by a signed license document from the license
server. If the server is unavailable, NexTerm keeps working with a cached license
for the offline grace period.

Enterprise terms:

- one activation code may be assigned to one customer, seat, team, or machine policy;
- activation JSON must be served from `/licenses/<CODE>.json`;
- license files must contain `key`, `edition`, `status`, `owner`, `expires_at`,
  `features`, and `signature`;
- server outage does not immediately block the app because cached licenses keep
  working offline;
- license enforcement is tamper-resistant, not impossible to remove from a Python
  desktop application.

Dev server:

```text
http://193.23.221.4/licenses/
```

Generate dev activation files:

```powershell
python tools\generate_licenses.py
```
