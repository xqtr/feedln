```
 _____             _ _       
|  ___|__  ___  __| | |_ __  
| |_ / _ \/ _ \/ _` | | '_ \ 
|  _|  __/  __/ (_| | | | | |
|_|  \___|\___|\__,_|_|_| |_|
                             
```

# Feedln

Feedln is a command-line RSS feed reader that allows users to manage and read their favorite feeds. It provides a simple interface to view, update, and categorize feeds, as well as mark items as read or unread.

## Features

- Feeds are stored/loaded from CSV file
- Can clean the database from orphan entries
- Edit the feeds file with external editor
- Can copy links, content, title etc. to clipboard, separately
- Can open links, video, images with external programs
- All links are displayed in separate screen, to select, copy, open
- Can extract text from feed entry to file
- Sort feeds, by Name/Title, Date
- Navigate through menus, with only left/right cursor keys, unified in all menus/screens

## Requirements

- Python 3.x
- Required libraries:
  - `feedparser`
  - `bs4` (BeautifulSoup)
  - `pyperclip`

You can install the required libraries using pip:
`pip install beautifulsoup4 feedparser pyperclip`

## Configuration

The application uses a configuration file (`Feedln.cfg`) to store user preferences. The following settings can be configured:

- `media`: Media player to use for playing media links (default: `mpv`).
- `browser`: Web browser to use for opening links (default: `firefox`).
- `xterm`: Terminal settings for opening the editor (default: `-fa 'Monospace' -fs 14`).
- `editor`: Text editor to use for editing the feed file (default: `nano`).

The file is optional, just to overwrite default values.

## Usage
Execute the application using the following command, no parameters needed.

   ```bash
   python feedln.py
   ```

Each screen/menu has its own help screen, press 'h' to see key shortcuts for each one.

## License

This project is licensed under the GPL3 License. See the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for any suggestions or improvements.

## Acknowledgments

- [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) for HTML parsing.
- [Feedparser](https://feedparser.readthedocs.io/en/latest/) for parsing RSS feeds.
