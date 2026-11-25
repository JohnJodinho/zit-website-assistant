# ZIT Assistant Widget — Design Proposal

**Status:** Waiting for approval. This is a proposal, not the finished widget.

## What the visitor experiences

The page first checks whether the assistant is available. If it is, a small
“Ask ZIT” button appears in the lower-right corner. It gives one gentle pulse
and then stays still. After about eight seconds, a small question prompt can
appear once. The visitor can dismiss it.

Selecting the button opens the chat. The welcome screen explains what ZIT can
help with and offers sample questions. A short privacy notice appears the
first time in that session. The visitor asks a question, sees the answer as it
arrives, and can open safe links or rate a completed answer. If something
fails, the widget explains the next step without showing technical errors.

The widget never saves conversation text in browser storage. Its session token
stays in memory, with a guarded session-storage fallback if needed.

## Screens and states

The small diagrams are not to scale. The phone and desktop versions share the
same content and state behavior.

### Loading availability

The loader checks the public configuration before showing anything. Until it
gets a clear answer, the panel uses a calm skeleton. If the service is
disabled, the launcher does not appear.

```text
+----------------------+
| ZIT Assistant        |
| [     ] [       ]    |
| [                 ]  |
+----------------------+
```

### Launcher closed

The desktop button is a cyan pill with an assistant mark and “Ask ZIT”.
On a phone it is a round icon button. It is at least 44 pixels wide and high.

```text
Desktop:                         Phone:
                         +----------------+
                         |  mark  Ask ZIT |
                         +----------------+
                                      (mark)
```

### Teaser nudge

After about eight seconds, one dismissible bubble appears beside the launcher:
“Questions about courses or applying? Ask me.” It appears once per session and
never returns after dismissal or opening the chat.

```text
             +----------------------------------+
             | Questions about courses or       |
             | applying? Ask me.             [x]|
             +----------------------------------+
                                      [Ask ZIT]
```

### Opening animation

The panel fades and grows into place in about 200 milliseconds. Reduced-motion
settings replace the movement with a simple fade. The opening does not move or
resize the school page.

```text
       +-------------------------+
       | ZIT Assistant   Online  |
       |                         |
       |       Welcome           |
       +-------------------------+
```

### Welcome screen

The assistant greets the visitor and says it can help with courses, fees,
applications, programmes, facilities, and contact information. Five
suggestion buttons offer common questions. Selecting one sends it as a
message.

```text
+----------------------------------+
| ZIT Assistant             Online |
| Hello! What can I help with?     |
| [Which courses do you offer?]    |
| [How do I apply?]                |
| [What are the fees?]             |
| [Tell me about programmes]       |
| [How can I contact ZIT?]         |
| [ Write a message...       Send ]|
+----------------------------------+
```

### First-use privacy notice

Before the first question, a dismissible notice displays the API's
`privacy_notice` value, or “Do not enter personal or confidential
information.” if no value is available. A privacy link appears only when
`VITE_PRIVACY_URL` is set. Dismissing it is remembered for that session.

```text
+----------------------------------+
| Please note                      |
| Do not enter personal or          |
| confidential information.   [x]  |
|                         Privacy  |
+----------------------------------+
```

### Typing indicator

After Send, the message appears immediately. Three quiet dots show while the
service is preparing its first text. The composer is disabled during that
time.

```text
You: How do I apply?
ZIT:  • • •
[                         Sending…]
```

### Streaming answer

Answer text appears as it arrives, with a small caret that disappears when
the answer finishes. The visitor can stop the stream; the visible text is
then labelled “Stopped” and is not rated as a completed answer.

```text
ZIT: Start by choosing the course that
     interests you. The application...
     |
[                         Stop      ]
```

### Finished answer, links, and feedback

Completed text uses a readable assistant bubble. Only safe HTTP or HTTPS links
provided by the API become link buttons. The visitor can copy the answer or
choose a thumbs-up or thumbs-down rating. A later rating can replace the
earlier one.

```text
ZIT: Choose your course and complete
     the application form.
     [Apply now] [View course]
     [Copy]                 [👍] [👎]
     Thanks for the feedback
```

### Error with retry

If a request fails, a kind message offers “Try again” and a contact link when
configured. A small Reference ID is shown to help support staff. Raw error
codes and stack traces are never shown.

```text
ZIT: I couldn't finish that request.
     Please try again.
     [Try again] [Contact ZIT]
     Reference: 00000000-...
```

### Rate limited

For a `429`, the widget says “Please wait a moment.” Send is disabled during
a short client-side countdown to prevent repeated requests. The API does not
provide a retry countdown, so the widget will not present the timer as an
exact server estimate.

```text
ZIT: Please wait a moment before
     sending another message.
[                         Wait…     ]
```

### Busy or capacity fallback

A finished fallback answer is still shown as a complete answer. A quiet note
explains it may be brief and points the visitor to admissions for full
details. The assistant status changes to “Busy right now”. A degraded answer
is not treated as a partial answer.

```text
ZIT: I can't look that up right now.
     Please contact admissions.
     Showing a quick answer. For full
     details, contact admissions.
     [Contact admissions]
```

### Session expired

For an expired session, the widget creates one new session and retries the
same question once. If that does not work, it shows the retry card rather than
repeating requests in a loop.

```text
You: How do I apply?
ZIT: Reconnecting...
     [Try again]
```

### Offline

When the browser reports that it is offline, a banner explains that the
connection is unavailable and Send is disabled. The banner clears when the
browser reconnects.

```text
+----------------------------------+
| You're offline. Reconnect to chat|
|                                  |
| [                         Send ]|
+----------------------------------+
```

### Assistant disabled or maintenance

When configuration says the assistant is disabled, the launcher stays hidden.
If the assistant becomes unavailable while a panel is open, it shows the
configured `maintenance_message` and a contact link if
`VITE_CONTACT_URL` is set.

```text
+----------------------------------+
| ZIT Assistant                    |
| The assistant is unavailable.    |
| [Contact ZIT]                    |
+----------------------------------+
```

### Very long answer

The panel keeps its size. The conversation scrolls inside it; the composer
stays in place. If the visitor scrolls up, automatic following pauses and a
“Jump to latest” button appears. Tables scroll inside their own answer bubble.

```text
+----------------------------------+
|       Conversation scrolls       |
|       ...                         |
| [Jump to latest]                  |
| [ Write a message...       Send ]|
+----------------------------------+
```

### Long message limit

Messages stop at 500 characters. A counter appears from 400 characters. If
the server reports a lower limit, the widget explains the limit beside the
composer.

```text
+----------------------------------+
| [Your message continues...       ]|
| 482 / 500                        |
| Please shorten your message.     |
| [                         Send ] |
+----------------------------------+
```

### Desktop, tablet, and phone

Desktop and tablet widths above 600 pixels use a floating card up to 400 by
640 pixels. It shrinks to fit a short window. At 600 pixels and below, the
panel is a full-screen sheet using the available screen height and phone safe
areas. Short and landscape phones use a compact header. The page behind the
phone sheet does not scroll.

```text
DESKTOP (>600 px)            TABLET (>600 px)            PHONE (<=600 px)
+--------------------+       +-----------------+         +---------------+
| school page   +---+|       | school page +--+|         | ZIT Assistant |
|               |chat||       |            |chat||         |---------------|
|               |   ||       |            |   ||         | full-screen   |
|               +---+|       |            +--+|         | conversation  |
+--------------------+       +-----------------+         | composer      |
                                                          +---------------+
```

On desktop, the launcher remains in the lower-right corner, 20 pixels from
the edges. On phones it also respects the safe-area inset. The open panel
uses the same anchor on desktop and fills the screen on phones. At 200 percent
zoom, it must stay usable without horizontal page scrolling.

## Look and feel

The widget has a dark theme inside its isolated frame. This follows the
approved visual direction and uses the website's real dark-mode colors. The
website source defaults to a light page theme, so the widget's separate frame
keeps the chat readable on either page appearance.

| Part | Value used in the proposal | Source |
| --- | --- | --- |
| Main blue | `#039fe0` | Website `--blue` |
| Blue hover | `#0286bd` | Website `--blue-d` |
| Light blue | `#4cc3f2` | Website `--blue-light` |
| Navy | `#0a2d4a` | Website `--navy` |
| Deep background | `#0b1622` | Website dark-mode `--bg` |
| Raised surface | `#0e1c2b` | Website dark-mode `--card` |
| Soft surface | `#102131` | Website dark-mode `--soft` |
| Main text | `#e9f1f8` | Website dark-mode `--ink` |
| Muted text | `#a9b7c4` | Website dark-mode `--muted` |
| Divider | `#1f3347` | Website dark-mode `--line` |
| Error | `#ff8a80` | Website dark-mode `--danger` |
| Heading font | Nunito Sans, then system sans-serif | Website `--font-head` |
| Body font | Roboto, then system sans-serif | Website `--font-body` |
| Main card corners | 26 pixels | Website `--radius` |
| Input and inner card corners | 16 pixels | Website `--radius-sm` |
| Pills | 999 pixels | Website `--radius-pill` |
| Dark shadow | `0 18px 40px rgba(0, 0, 0, 0.35)` | Website dark-mode `--shadow` |
| Blue shadow | `0 18px 40px rgba(3, 159, 224, 0.16)` | Website `--shadow` and `--blue-rgb` |
| Common spacing | 8, 10, 12, 14, 16, 20, 24, 28, and 30 pixels | Existing website buttons, cards, and layout |
| Motion | 200 milliseconds, ease | Existing website buttons and header |

The header uses the website's soft navy-to-blue gradient. Text and controls
will be checked for WCAG AA contrast. The page input stays at least 16 pixels
to avoid mobile browser zoom. Buttons have visible focus, labels, and touch
targets at least 44 by 44 pixels. Motion respects reduced-motion settings.

The website's logo images exist but are large wordmark PNGs. The small
approval preview uses a simple shield-like Z mark so it stays self-contained.
For the finished widget, the existing emblem will be cropped and optimized
before it is copied into the widget.

## Loading and placement on the school website

The checked website source is a React and Vite single-page app. Its
`misc/zit-website/index.html` contains the root element and the Vite module
script. The web team will add one asynchronous loader script immediately
before the closing body tag, after the current module script. It will not be
added inside the React root, and it will not require a change to the page
components.

The loader first reads `GET /api/v1/config`. It shows nothing when the
assistant is disabled. It creates the iframe only on the visitor's first
open. The launcher and page are isolated from the school page's CSS in a
Shadow DOM and a sandboxed iframe. Messages in either direction are accepted
only from the exact expected origin and window. The widget receives only the
page path and title. Links are limited to safe HTTP or HTTPS destinations.

The current website source has these relevant layers:

- The sticky header uses z-index 60.
- The navigation dropdown uses z-index 90.
- The gallery lightbox uses fixed positioning and z-index 100.
- The keyboard skip link uses fixed positioning and z-index 200 at the
  upper-left corner.
- Hero controls use z-index 5 inside the hero; they are not fixed.
- No fixed WhatsApp button, back-to-top button, or cookie banner was found in
  the checked source.

The proposed loader layer is z-index 95. This puts the launcher above normal
page content, the header, and the navigation dropdown, but below the gallery
lightbox and focused skip link. It stays at the lower-right edge rather than
covering the header. On phones, the open sheet deliberately covers the page
and locks background scrolling. The source may be stale, so the owner should
confirm live floating elements before the web team adds the tag.

No Content-Security-Policy meta tag was found in the checked `index.html`.
The deployed site may set a policy in response headers; the web team must
allow the loader and widget host in its script, frame, and connection rules.

## How the owner will try it

The approval page is `widget/design-preview.html`. Open it directly in a
browser; it uses no network requests. It shows a phone frame and a desktop
frame at the same time. Its buttons switch both between welcome,
mid-conversation, streaming, error, and rate-limited examples. All names,
questions, and answers in it are fake.

After approval, the full local playground will be served by `npm run dev`.
Its device switcher will offer Phone (390 by 844), Small phone (320 by 568),
Tablet (768 by 1024), Laptop (1366 by 768), Desktop (1920 by 1080), Landscape
phone (844 by 390), and Full window. The playground will allow the owner to
choose the local backend or a mock backend.

The mock-state controls will cover a normal answer with links, a slow first
word, a long answer with a table and list, an error after partial text, a
connection ending without `done`, rate limiting, session expiry and recovery,
assistant disabled, maintenance, a busy fallback, a message that is too long,
and offline mode. The production preview will also be served through `npm run
preview`.

The local API address will come from `.env.development` and default to
`http://127.0.0.1:8000`. The production example will use the public Render
API address. Turnstile support will stay off when `VITE_TURNSTILE_SITE_KEY`
is blank; in that case session creation sends an empty JSON object. A site key
enables the challenge flow.

## Not included

This version does not include user accounts, saved chat history across visits,
file or image uploads, voice, multiple languages, a human handoff, analytics
dashboards, a light theme, website-specific theme settings, or backend
changes. The widget will not create a staff-only rollout bypass.

## Files and checks planned after approval

The implementation will stay in `widget/` and the named root-level widget
documents. It will use the required strict TypeScript and Tailwind stack.
The planned files are:

- `widget/src/api/types.ts`, `client.ts`, and `sse.ts` for API shapes,
  requests, and stream reading.
- `widget/src/state/session.ts` and `chat.ts` for session handling and chat
  state.
- `widget/src/components/Launcher.tsx`, `ChatPanel.tsx`, `MessageList.tsx`,
  `Message.tsx`, `Composer.tsx`, `SuggestionChips.tsx`,
  `FeedbackButtons.tsx`, `MarkdownContent.tsx`, and `StatusBanner.tsx`.
- `widget/src/styles/tokens.css` and `components.css` for the one shared
  design-token set and shared component styles.
- `widget/src/loader/loader.ts` and `loader.css` for the isolated page
  launcher and its Shadow DOM styles; the build creates `widget/public/loader.js`.
- `widget/src/dev/playground.ts`, `mockBackend.ts`, and `widget/playground.html`
  for the owner playground and simulated responses.
- `widget/src/test/` for the Vitest and jsdom tests, and
  `widget/scripts/check-styles.ts` for the style rules check.
- `widget/.env.example`, `widget/.env.development`, and `widget/vercel.json`
  for public build settings and hosting headers.
- `widget/package.json`, its lockfile, TypeScript/Vite/Tailwind/ESLint
  configuration, and `widget/index.html`.
- `LOCAL_TESTING.md`, `WIDGET_REPORT.md`, `VERCEL_HANDOVER.md`, and
  `WIDGET_STATE.md` for owner instructions, verification results, handover,
  and progress.

Some component and test filenames may be grouped differently if that makes
the finished structure clearer; the complete required behavior and checks
will remain the same.

`npm run verify` will report typecheck, lint, style-rule checks, jsdom tests,
production build, bundle budgets, and absence of mock code in the production
files. The tests will cover stream boundaries and errors, session recovery,
rate limits, safe links, feedback, loader isolation, and keyboard behavior.
Loader tests will check visibility, opening, closing, focus return, and
isolation from school-page styles. The local-backend checks will cover CORS
preflight and one streamed question. The stage also allows one live-model
question within its call cap. Production health and config will be checked
with curl. No browser automation or screenshots will be used; the owner will
do the visual checks in the playground.
