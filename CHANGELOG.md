## Feedln Changelog

### Version 1.0.1 (2024/12/23)

- Added logging function
- Instead of retrieving feed with feedparser, requests in now used
- Added timeout, for requests and logging feeds that have not been retrieved

### Version 1.0.2 (2025/01/04)
- Instead of deleting the database file, now every table is dropped and recreated. No need to restart program
- Minor database fixes
- Added ESC key to also behave like left cursor key

### Version 1.0.3 (2025/01/19)
- Added Browse feature. You can Press TAB in a Category and browse all feeds, with newest and unread items on top
- Moved Database size to header
- Added more information when updating feeds on the footer
- Minor errors, fixed

### Version 1.0.4 (2025/02/03)
- Default values for Browser, Editor, Media Player are taken from OS environment variables (BROWSER, EDITOR, PLAYER). If a settings file exists, the values are replaced from the one in the settings file. Otherwise, if no environment variables are set and no settings file exist, the program sets default values, firefox, mpv and nano.


### Version 1.0.5 (2025/02/03)
- Added Speak Text support using espeak Linux tool. Press S to see a menu to select what to convert to speach. Press X to cancel speaking.
- Added function to export feeds in OPML file. Press O in category listing.
- Added Search Function in main categories. Press / to enter a search term and select where to search (Title, Summary, Text)
- Added feature to add a RSS Feed, directly from Feedln, with prompts
- Added an external tool (opml2csv.py) to convert OPML files to the default format for Feedln
- Feedln now accepts a parameter to use different files, with RSS feeds. It will also use a different database file. This way, you can have multiple files, containing different kind of RSS feeds