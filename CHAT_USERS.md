# Per-user chat routing and personas / 按 user 定向对话与人设

`POST /v1/chat/completions` accepts the standard OpenAI `user` field.

- **No `user`**: behavior is unchanged. Each request is stateless, the full
  history is sent again, and accounts rotate with automatic failover.
- **With `user`**: the request goes to the one account bound to that user and
  continues that user's own muse.ai thread.

## Rules

| Topic | Behavior |
|---|---|
| Switch | `MUSE2API_CHAT_USER_ROUTING=0` ignores `user` and keeps every request on the old stateless path (for clients that already send `user` for other reasons). Default `1`. |
| Account binding | Set by an admin (`PUT /admin/chat-users/{user}`), or bound automatically on first use (`MUSE2API_CHAT_USER_AUTO_BIND=1`, default). The binding is kept until an admin changes it. |
| Isolation | Each user has its own muse thread. With `MUSE2API_CHAT_USER_EXCLUSIVE=1` (default) one account serves at most one user, so users also never share an account's workspace or thread list. |
| Busy account | The request waits up to `MUSE2API_CHAT_USER_QUEUE_TIMEOUT` seconds (default 120; 0 = no wait), then fails with HTTP 429 `rate_limit_error`. While it waits it holds no generation slot. |
| Unusable account | A disabled, deleted or cookie-less bound account returns HTTP 503 with a clear message. |
| No failover | A user request never moves to another account, not even on errors. |
| Persona | The user's persona (custom system prompt) is sent once, at the top of the first message of a new thread. The client's own `system` messages follow it. |
| Follow-ups | The stored thread is reopened and only the turns after the last `assistant` message are sent. The persona and earlier turns are not sent again. |
| New thread | Send `"new_thread": true`, or call `POST /admin/chat-users/{user}/reset`. The next message opens a new thread and injects the persona again. |
| Lost thread | If muse.ai cannot open the stored thread (deleted or redirected), a new thread is opened on the same account with the persona and the full transcript of the request. |
| Persona edits | They apply to the next new thread. Reset the thread to use a new persona now. |
| Account change | Rebinding a user to another account forgets the old thread. Rebind and delete return 409 while the account runs a task, so they never race with a send. A request that waited in the queue and finds its user rebound returns 409. |
| Reused accounts | The old user's threads stay in the muse.ai account. If you bind that account to a different user, use a fresh account when the history must stay private. |
| `/v1/responses` | Unchanged (stateless, rotating). |

## Request

```bash
curl http://localhost:18610/v1/chat/completions \
  -H "Authorization: Bearer $MUSE2API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"muse-spark","user":"alice","messages":[{"role":"user","content":"你好"}]}'
```

Clients can keep sending the full history (OpenAI style) or only the newest
message. Either way only the new turns reach muse.ai. The request must end
with new content (a `user` or `tool` message), otherwise it returns HTTP 400.

## Admin API (Bearer key)

| Method and path | Purpose |
|---|---|
| `GET /admin/chat-users` | List users, bound accounts, personas and thread state. |
| `GET /admin/chat-users/{user}` | One user. |
| `PUT /admin/chat-users/{user}` | Body `{"account_id": "...", "persona": "..."}`. Only the fields in the body change; `null` clears a field. Binding an account that another user holds returns 409 in exclusive mode. |
| `POST /admin/chat-users/{user}/reset` | Forget the thread; the next request starts a new one with the persona. |
| `DELETE /admin/chat-users/{user}` | Remove the user. |

```bash
curl -X PUT http://localhost:18610/admin/chat-users/alice \
  -H "Authorization: Bearer $MUSE2API_KEY" -H "Content-Type: application/json" \
  -d '{"account_id":"<id from GET /admin/accounts>","persona":"你是 Alice 的私人助理……"}'
```

The state is stored in `data/chat-users.json` (inside the Docker data volume).
You can also edit it by hand; it is reloaded when it changes. If the edited
file is not valid JSON, the last valid state stays in use and the broken file
is kept as `chat-users.json.invalid-<time>` on the next write.

```json
{"version": 1, "users": {"alice": {"account_id": "3f2a9c1b7d4e", "persona": "你是 Alice 的私人助理……"}}}
```

## Verify

```bash
python tests/test_chat_user_routing.py
```

The test uses a fake muse.ai engine. It checks binding, isolation, busy and
disabled accounts, one-time persona injection, follow-ups that send only new
turns, lost-thread recovery, the admin API, and that requests without `user`
keep the old path. A live check needs a real account: send two requests with
the same `user` and confirm in muse.ai that both messages are in one thread
and that the persona appears only at its top.
