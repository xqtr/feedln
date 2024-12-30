## Feedln Changelog

### Version 1.0.1 (2024/12/23)

- Added logging function
- Instead of retrieving feed with feedparser, requests in now used
- Added timeout, for requests and logging feeds that have not been retrieved

### Version 1.0.2 (2024/12/25)

- Instead of deleting the database file, now it drops the database and recreate the feeds
- Now you can add multiple categories to each feed, to appear. For example the following feed will appear in all categories/tags
`KevoBato,https://www.youtube.com/feeds/videos.xml?channel_id=UCGp9AMLS0Q-xj6zqzi84M3g,Batocera;Youtube;RetroGaming`
Each category should be separated with a semicolon character ; 
- Reorganized database to reflect above changes

### Version 1.0.3 (2024/12/30)

- Added sort function for categories
- Improved sort function for feeds. Now you can sort, also by Unread feed items count.
- Fixed timeout issues with feed retrieval
- Improved error handling for malformed feeds
- Added retry mechanism for failed requests
- Updated logging format for better debugging
- Now you can clean the database from orphan feeds by pressing # key. 
- Fixed behavior of PgUp/PgDn keys
