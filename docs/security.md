# Permissions and security

What the guide may do on your computer, what it never does, and what apps are allowed. To report a security problem, see [SECURITY.md](../SECURITY.md).

## Permissions and security

Plugins run unsandboxed inside `omarchy-shell`, so here is everything this one
touches.

- **Registers one Hyprland shortcut at runtime**: `hyprctl eval` runs
  `hypr/om-pg.lua`, which binds the shortcut (Super + Alt + T unless you change
  it) to a message for the guide over Hyprland's event socket. It runs no
  programs and reads or writes no files. It's registered again after a
  Hyprland config reload (which clears it) and taken out when the guide is
  turned off. Your Hyprland config is never edited. `hyprctl -j binds` is read
  first, so a shortcut another binding already uses is left alone (Settings
  says which). Both hyprctl calls are bounded in output and time.
- **Keeps the screen awake only as you set it** (Settings → General → Keep
  the screen awake, and the screen saver): through a Wayland idle inhibitor
  on its own window while it's on screen, which Omarchy's idle respects and
  which ends with the window. Omarchy's settings and its stay-awake switch are
  never changed. A press on your paired phone runs Hyprland's
  `hl.dsp.force_idle(0)` (idle timers start over, as for a key; a hold like a
  playing video's still wins). When Omarchy's own screen saver opens, the
  guide hides its full-screen layer and focuses that window by its address
  (`hl.dsp.focus`), only on the screen that has focus, so Omarchy's screen
  saver and lock work as they do everywhere else.
- **The bar icon** (`BarWidget.qml`) only reads `~/.config/om-pg/settings.json`
  (whether to show itself, and the shortcut for its tooltip) and asks the
  shell to open or close the guide.
- **Reads** the plugin's own files, `~/.config/om-pg/channels.json`, and any
  file you point the add box at (regular files under 5 MB only, so `/dev/zero`
  or a huge file can't hang the shell). Nothing in a file is ever run: it is
  only searched for YouTube links. A background picture you choose (or your
  Omarchy wallpaper) is only shown as an image. It reads your Omarchy theme's
  `colors.toml` for themes that follow its colors (only `name = "#hex"` lines
  are used). With the screen saver on, it reads Omarchy's backgrounds (its
  themes', your own themes' and ones you've added) and the pictures in your
  screen saver folder (`~/Pictures/Screen Saver`, or the one you picked): each
  checked by `bin/om-pg-apps` before it's listed (a plain file, never a link,
  a real PNG, JPEG or WebP by its first bytes, at most 40 MB and 8192 pixels a
  side, up to 500).
- **Writes** `~/.config/om-pg/channels.json` (your channels),
  `~/.config/om-pg/settings.json` (which categories to show, logos on or off,
  your colors and style, Home), `~/.config/om-pg/library.json` (your movies
  and My List) and `history.json` (where you stopped in each, and a YouTube
  video's channels by address, at most 100, for the channel lock), both readable
  by you alone, `~/.config/om-pg/themes/` (themes you or an agent
  saved, each a folder with copies of its pictures, readable by you alone,
  written as one confirmed transaction by `bin/om-pg-apps`), with apps with
  code, `~/.config/om-pg/app-screens.json` (how you've customized their
  screens, 64 KB at most) and `~/.config/om-pg/app-pictures/` (copies of
  pictures you picked for an app's screen or Home), both readable by you
  alone, `~/.cache/om-pg/listings.json` (saved listings and today's lineups),
  `~/.cache/om-pg/snapshot-<run>-<n>.png` (pictures of the guide, only when the
  `snapshot` or `appSnapshot` command asks: the newest five, readable by you
  alone), with My Videos on,
  `~/.cache/om-pg/videos.json` and `~/.cache/om-pg/thumbs/` (each video's
  length and a picture from it, readable by you alone), with program
  listings, `~/.cache/om-pg/epg.json` (your channels' shows for today and
  tomorrow, readable by you alone), with logos on,
  `~/.cache/om-pg/logos/` (one small image per channel), and, with the screen
  saver, `~/.config/om-pg/lock.json` (the channel lock: its passcode only as a
  salted scrypt hash, the locked channels and its options; readable by you
  alone, written whole by `bin/om-pg-apps`, never `settings.json`), with the screen
  saver, `~/.cache/om-pg/saver/` (copies of the pictures it's showing, copied
  from the very file that was checked, readable by you alone: the newest
  twelve, gone when it closes). It makes your screen saver folder (only inside
  your home folder) when you open it from Settings. Nothing else.
- **Runs** `yt-dlp` (listings), `find` (listing your channel-list files, or
  pictures for a background, for the picker; hidden folders are skipped, but
  Omarchy's backgrounds are included, or folders for My Videos; browsing, the
  one folder you're in), `stat`
  (checking a file before reading it), `bin/om-pg-streamer` (Python, while
  the guide has been opened this session), and, with My Videos on,
  `bin/om-pg-videos` (Python: lists the videos in your folder, and runs
  `ffprobe` for each one's length and `ffmpegthumbnailer` for its picture,
  once per video; both come with Omarchy), and, with program listings,
  `bin/om-pg-epg` (Python: downloads the listings you added, reads them as
  they come and keeps your channels' shows), with the screen saver,
  `bin/om-pg-apps saver-pictures`, `saver-take` and `saver-folder` (listing
  and checking its pictures, copying one before it's shown, making your folder),
  and `xdg-open` (your screen saver folder, in your file manager, when you
  ask), and, for the channel lock, `bin/om-pg-apps lock-read`, `lock-check`,
  `lock-passcode`, `lock-save` and `lock-reset` (a passcode goes to it on its
  stdin, never its command line, and the guide never keeps one after the
  check), and `pkexec /usr/bin/true`: the system's password prompt, as the
  firewall change asks, running nothing else, one at a time, only when you
  reset a forgotten passcode, turn on Third-party apps or Developer mode, or
  install a signed app file; each happens only if the password was given and
  what you were asked about hasn't changed meanwhile. For Third-party apps,
  `bin/om-pg-apps app-inspect` opens a picked `.tvapp` without following links,
  caps it at 25 MB, accepts exactly its four plain members, verifies its
  Ed25519 signature and package, and contacts nothing. The package is staged
  privately and installed only after the password prompt approves that exact
  app, key and file. With an update address, `app-update-check` fetches only a
  capped signed release note through `lib/appnet.py` (HTTPS, public addresses,
  TLS and redirects checked) and only while the Third-party apps switch is on. The guide
  shows the exact package address, version, size, pinned key and asks;
  `app-update-prepare` fetches the package only after Agree, only from the
  update address's host, and verifies its signed size and SHA-256. `app-current`
  and `install` recheck the accepted state before putting it in
  `~/.local/share/om-pg/apps/`, read-only. Every start, `verify` checks the
  kept package, release, signature, key, monotonic state, cumulative
  withdrawals and installed files without using the network. A
  passcode typed on the phone remote comes as a `code` command (4 to 8
  digits, checked by `bin/om-pg-remote`, only from a paired phone), crossing
  your network in plain HTTP like the remote's other presses, and is never
  written anywhere.
  Arguments are passed directly, never through a shell, and every URL is put
  after `--`, so nothing in a channel list can become a yt-dlp option.
- **Fetches** from YouTube: listings, each channel's live streams, the videos
  themselves and, with logos on, channel avatars from YouTube's image servers
  (`yt3.googleusercontent.com`, `yt3.ggpht.com`; https only, under 512 KB, and
  only when every address is a public one). A redirect is checked the same
  way, so an avatar link can't leave those servers. A YouTube media playlist
  is fetched the same way (https, public addresses, 2 MB at most). For IPTV, it
  fetches the playlists you add (with `curl`: http or https, 20 MB and 30 s at
  most), plays their streams (http or https), and, with logos on, their logos
  (images only, under 512 KB). A logo or a program-listings link is resolved
  first and again after every redirect. A public address is fetched, and so is
  one on your own network, where a home media server lives. This computer, a
  link-local address (including a cloud machine's metadata address) and every
  other special range is not. A login on a link is sent only back to that same
  scheme, host and port. A redirect that brings its own login is sent that
  login, never the original. Listings stop at 400 MB compressed and 512 MB once
  unpacked, and an xz file can't reserve more than that to decode. Links to
  anywhere else are dropped, whether pasted,
  imported, or hand-edited into the saved list.
- **Listens** on `127.0.0.1` (the streamer, on a random port). Every request
  must carry a secret made at startup, so web pages and other programs can't
  use it; it answers only `/<secret>/play/<11-character video id>.m3u8` and
  `/<secret>/logo/<channel id>.jpg`.
- **Shows** channel names and video titles as plain text, never as rich text,
  so a name from a shared list can't load images or links.
- **Listens on your network only if you turn the phone remote on** (port
  24750, `bin/om-pg-remote`). It answers private addresses only, pairs phones
  with a short-lived single-use code, keeps a hash of each phone's token in
  `~/.config/om-pg/remotes.json` (readable by you alone), accepts a fixed set
  of remote commands and nothing else (no files, no links, no shell), and
  rejects requests from other websites. It's plain HTTP: someone already on
  your network who watches its traffic could copy a phone's token and change
  your channel. It stops when you turn it off or the shell exits.
- **Changes the firewall only when you agree to it**, through the system's
  password prompt: one `ufw` rule for that port from your local network,
  labelled `om-pg phone remote`, offered for removal when you turn the remote
  off. It runs `systemctl is-active ufw` to know whether a rule is needed,
  and `qrencode` for the pairing QR code.
- **Links its AI agent skill only if you turn it on** (Settings): a link
  named `program-guide` to the plugin's `skills/program-guide`, in each agent
  skill folder that exists (above), made and taken out by `bin/om-pg-skill`
  (`ln`, `rm`). It never replaces anything else with that name, and takes out
  only links to this skill.
- **Saves a copy of the agent skill only when you press Save the agent
  skill** (Settings → General): its SKILL.md, as `Uber TV agent skill.md` in
  your Downloads folder, written beside it and renamed into place by
  `bin/om-pg-skill save`, so a link already at that name is replaced, never
  written through. Agents and scripts can't start it.
- **Looks for a newer Uber TV only if you turn update notifications on**
  (Settings → About), or when you press Check for updates: `git ls-remote
  --tags` to the address it was installed from (names only; nothing is
  downloaded), when the shell starts and every 12 hours, never asking for a
  password (`GIT_TERMINAL_PROMPT=0`, ssh in batch mode), 25 s and 1 MB at
  most. A newer version's release notes fetch its one commit, and of its
  files only `CHANGELOG.md` where the server allows it, into a private folder
  in `$XDG_RUNTIME_DIR` removed right after (`bin/om-pg-update`). Nothing is
  installed: updating stays `omarchy plugin update`.
- **Backs up only when you ask** (Settings → About): one file in `Uber TV
  backups` in your Documents folder, readable by you alone in a folder only
  you can open, written whole: your channels, settings, library, Continue
  watching, themes and the pictures you picked; never paired phones, the
  channel lock, app sign-ins or apps. Restoring checks the file as it reads
  it (only those names, regular files, sizes, JSON that reads), swaps its
  parts in, and puts back what it swapped if a step fails; the phone remote's
  settings stay as they are (`bin/om-pg-backup`).
- **Resets everything only when you ask** (Settings → Developer → Reset Uber
  TV, after a box that asks first): with a channel lock set it asks for the
  computer's password, and taking out the phone remote's firewall rules asks
  for it too. It saves a backup, stops the TV, the phone remote, the apps and
  the agent skill's links, then moves `~/.config/om-pg`, `~/.local/share/om-pg`
  and `~/.cache/om-pg` aside (never through a link), leaves empty ones in
  their place, and deletes what was moved. If a move fails, nothing is
  deleted.
- **Answers commands** from your own login session (`omarchy-shell om-pg …`,
  through the shell's IPC socket, like every plugin's). They change only the
  guide: channels, themes, colors, what's shown. A theme is checked before
  it's saved: known slots, elements and settings, colors as hex (or an
  Omarchy color's name), numbers in range, installed fonts, an outline as an
  SVG path's letters and numbers only, a picture as a full path to an image
  (copied into the theme's folder: a regular file of 40 MB at most, `cp`,
  `stat`). Pictures are only ever shown as images. A theme is data: it picks
  among the layouts and parts the guide draws itself, so nothing in a theme
  is ever run. A theme is saved as one confirmed transaction (its pictures
  checked and copied in under new names, its `theme.json` written whole,
  read back, renamed into place and synced) and put on only once the disk has
  confirmed it; theme changes go one at a time. A picture you pick (for a
  theme, Home or an app's screen) is opened without following links and
  checked through that open file (a plain file of 40 MB at most, PNG, JPEG or
  WebP by its first bytes, at most 8192 pixels a side and 40 MP), and only
  its copy is shown. `snapshot` and `appSnapshot` write a picture of the
  guide only, as `snapshot-<run>-<n>.png` in the cache folder (written whole, then
  renamed), and never while a sensitive screen is up: the phone remote's box
  (its pairing code), an app's sign-in, its settings or a certificate to pin,
  or a text field; one that comes up while the picture is taken drops it.
  **Agents and apps' screens:** answers name rows and items only by the
  guide's own handles (no app id, title or other text an app sends ever
  reaches an agent); `setAppScreen` takes at most 64 KB and only handles;
  `openApp` opens only an app that comes with the guide, and never plays,
  presses an app's button, signs in or opens its settings; everything it
  sends is checked again right before it goes, and anything you do yourself
  ends it. There's no command
  for the phone remote or the firewall, or to turn apps on, install, update
  or remove them.
- **Apps, only if you turn them on** (Settings → Apps; see [Apps](apps.md)):
  `bin/om-pg-apps` (Python) downloads the catalog and its signature (https
  only, redirects only to https; 2 MB at most), checks the signature with
  `ssh-keygen`, downloads the packages it lists (20 MB at most) and their
  icons (512 KB), unpacks one into a private folder in
  `~/.cache/om-pg/app-staging/` (cleared after a day) and, once you say
  Install, moves it to `~/.local/share/om-pg/apps/`, read-only. It keeps
  `~/.cache/om-pg/apps-catalog.json` (the catalog as checked) and
  `~/.cache/om-pg/app-icons/`. What's installed is in
  `~/.config/om-pg/apps.json`. Opening an app runs `omarchy-launch-webapp`
  with its link as one argument (never through a shell; Omarchy's
  launch-or-focus helper isn't used, since it runs its arguments through
  `eval`). Nothing in a launcher package is run. A signed `.tvapp` picked
  under Third-party apps is installed under its developer-key identity; the
  same id under another key has separate data and replaces it only after the
  new identity is installed and recorded. Turning off Third-party apps stops those
  apps and cancels their update-note or package fetches.
- **Apps with code** (Scores and Jellyfin, which come with the guide, one
  from an unsigned file in Developer mode, or a signed `.tvapp`) run only in
  bubblewrap, through
  `bin/om-pg-apprun`, which makes every request for them: only to the exact
  sites they listed (https, public addresses, GET and HEAD, plus the
  methods an API 4 app listed for a site it may change things on) or the
  server you chose. A redirect is checked again with the method it's sent
  with; a write is never carried to another site, and every header the app
  set is dropped when the site changes. Before you install one you see each
  site it can change things on, and an update adding one waits for you. What
  each request reached is kept as daily totals per site, its **Activity**
  (`~/.local/state/om-pg/app-activity/`, readable by you alone, 1 MB an app at
  most, 90 days): never a path, a query, a header or a body. Its storage,
  secrets and log are kept as [Apps](apps.md) says; removing it removes all
  of them. A password you type to sign in to one (its box is the guide's
  own, keyboard only) goes to the helper on its stdin and to the app once;
  nothing keeps it, and it's kept out of the app's log for its whole run.
- **Publishing a signed app file** ([docs/sources.md](sources.md)) is by hand,
  in a terminal. `om-pg-apps app-key` runs `ssh-keygen -t ed25519` and records
  one permanent private publisher workspace; `app-file` checks, packs and
  signs a `.tvapp` and optional update files; `app-revoke` signs a cumulative
  withdrawal. The workspace is opened no-follow and locked for the run, its
  recorded release is verified before building on it, and every release is a
  new exclusive folder—nothing published is overwritten. The guide never runs
  these commands, and nothing they make is uploaded: the developer copies the
  files themselves.
- **Registers** as a media player on your session bus
  (`org.mpris.MediaPlayer2.programguide`) while the TV is on; nothing outside
  your login session can see it.
