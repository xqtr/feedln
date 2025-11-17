#!/usr/bin/python3
import curses
import csv
import feedparser
import sqlite3
import requests
import time
from bs4 import BeautifulSoup
import os
import subprocess
import pyperclip
import configparser
from textwrap import wrap
import re
import logging
import threading
from datetime import datetime
import argparse

program = "Feedln"
version = "1.0.5"
database = "feedln.sq3"
feedfile = "feedln.csv"
cfgfile = "feedln.cfg"
logfile = "feedln.log"
reqtimeout = 8

browser = os.environ["BROWSER"]  # get settings from environment
media = os.environ["PLAYER"]  # "mpv"
xterm = "-fa 'Monospace' -fs 14"
editor = os.environ["EDITOR"]

SPEAK = "espeak"
FETCHONLOAD = False


class InterruptibleTTS:
    def __init__(self):
        self.speaking = False
        self.enabled = False

    def speak(self, text):
        def run():
            self.speaking = True
            os.system(SPEAK+' "'+text+'" >/dev/null 2>&1')
            self.speaking = False
        if not self.enabled: return
        self.thread = threading.Thread(target=run)
        self.thread.start()

    def stop(self):
        if not self.enabled: return
        if self.speaking:
            os.system("killall espeak >/dev/null 2>&1")
            self.speaking = False


logging.basicConfig(
    filename=logfile,  # Log file name
    level=logging.INFO,      # Log level
    format='%(asctime)s - %(levelname)s - %(message)s'  # Log message format
)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=f'{program} v{version} - RSS Feed Reader')
    parser.add_argument('-f', '--file', 
                        help='Path to CSV file containing feeds (default: feedln.csv)',
                        default=feedfile)
    parser.add_argument('-F', '--fetch', action='store_true',
                        help='Fetch all feeds, on load')
    return parser.parse_args()


def log_event(message):
    """Log an event with the specified message."""
    logging.info(message)  # Log the message as an info level event


def load_config():
    global media, xterm, editor,reqtimeout, media, browser, xterm, editor, reqtimeout
    config_file = cfgfile  # Assuming cfgfile is the path to your config file
    if os.path.exists(config_file):
        config = configparser.ConfigParser()
        config.read(config_file)
        if 'Settings' in config:
            media = config['Settings'].get('media', media)
            browser = config['Settings'].get('browser', browser)
            xterm = config['Settings'].get('xterm', xterm)
            editor = config['Settings'].get('editor', editor)
            reqtimeout = int(config['Settings'].get('reqtimeout', reqtimeout))
    else:
        if not editor: editor = "nano"
        if not browser: browser = "firefox"
        if not media: media = "mpv"


def check_feed_file():
    global feedfile
    if not os.path.exists(feedfile):
        with open(feedfile, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Name", "URL", "Category", "Tags"])  # Write header
            writer.writerow(["CP737 Blog", "https://cp737.net/blog.rss", "xqtr", ""])  # Add a default feed


def is_program_installed(program_name):
    try:
        # Using 'which' command
        subprocess.run(['which', program_name], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError:
        return False


# Database setup
def setup_database():
    global database
    conn = sqlite3.connect(database)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feeds (
            id INTEGER PRIMARY KEY,
            name TEXT,
            url TEXT UNIQUE,
            tags TEXT,
            category TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feed_categories (
            feed_id INTEGER,
            category_id INTEGER,
            FOREIGN KEY (feed_id) REFERENCES feeds (id),
            FOREIGN KEY (category_id) REFERENCES categories (id),
            PRIMARY KEY (feed_id, category_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feed_items (
            id INTEGER PRIMARY KEY,
            feed_id INTEGER,
            title TEXT,
            summary TEXT,
            content TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            last_updated INTEGER NOT NULL DEFAULT 0,
            created INTEGER NOT NULL DEFAULT 0,
            link TEXT,
            UNIQUE(feed_id, title),
            FOREIGN KEY (feed_id) REFERENCES feeds (id)
        )
    """)
    conn.commit()
    return conn


def confirm(stdscr,text):
    footer(stdscr,text)
    stdscr.move(curses.LINES-1, 1)
    curses.curs_set(1)  # Show cursor

    confirmation = ""
    stdscr.move(curses.LINES-1, len(text))
    while True:
        key = stdscr.getch()
        if key == curses.KEY_BACKSPACE or key == 127:  # Handle backspace
            confirmation = confirmation[:-1]
        elif key == ord('\n'):  # Enter key
            break
        elif key < 256:  # Only accept printable characters
            confirmation += chr(key)

        stdscr.addstr(curses.LINES-1, len(text), confirmation+" ", curses.color_pair(2)|curses.A_BOLD)  # Display current input
        stdscr.move(curses.LINES-1, len(text)+len(confirmation))
        stdscr.refresh()

    curses.curs_set(0)
    if confirmation.lower() == 'yes':
        return True
    else:
        return False


def clean_database(stdscr):
    global database,feedfile
    if confirm(stdscr,"Clean old feed items? Write 'yes' to confirm:"):
        try:
            conn = sqlite3.connect(database)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM feeds")
            feeds = cursor.fetchall()
            for feed in feeds:
                cursor.execute(f"DELETE FROM feed_items WHERE feed_id = {feed[0]} ORDER BY last_updated DESC LIMIT 10")
            conn.commit()
        except Exception as e:
                footer(stdscr,f"Error: {e}",1)
                stdscr.refresh()
                time.sleep(2)
    else:
        footerpop(stdscr,"Reset canceled.")


def delete_database_file(stdscr):
    global database,feedfile
    if confirm(stdscr,"Reset database? Write 'yes' to confirm:"):
        try:
            conn = sqlite3.connect(database)
            cursor = conn.cursor()
            # Drop existing tables
            cursor.execute("DROP TABLE IF EXISTS feed_items")
            cursor.execute("DROP TABLE IF EXISTS feed_categories")
            cursor.execute("DROP TABLE IF EXISTS categories")
            cursor.execute("DROP TABLE IF EXISTS feeds")
            # Recreate tables
            conn = setup_database()  # Recreate the database and tables
            load_feeds_to_db(feedfile, conn)
            footer(stdscr,f"Database has been reset and tables recreated.")
            stdscr.refresh()
            time.sleep(1)
        except Exception as e:
            footer(stdscr,f"Error: {e}",1)
            stdscr.refresh()
            time.sleep(2)
    else:
        footerpop(stdscr, "Reset canceled.")
    curses.curs_set(0)


# Export all feeds to OPML file
def export_opml(stdscr, conn, filename="feedln.opml"):
    """
    Export feeds from database to OPML format
    Parameters:
        stdscr: Curses window object
        conn: Database connection
        filename: Output OPML filename (default: feedln.opml)
    """
    try:
        cursor = conn.cursor()
        # Get all feeds with their categories
        cursor.execute("""
            SELECT f.name, f.url, GROUP_CONCAT(c.name) as categories, f.tags
            FROM feeds f
            LEFT JOIN feed_categories fc ON f.id = fc.feed_id
            LEFT JOIN categories c ON fc.category_id = c.id
            GROUP BY f.id
        """)
        feeds = cursor.fetchall()

        # Create OPML structure
        opml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        opml += '<opml version="2.0">\n'
        opml += '  <head>\n'
        opml += f'    <title>Feedln Export</title>\n'
        opml += f'    <dateCreated>{time.strftime("%a, %d %b %Y %H:%M:%S %z")}</dateCreated>\n'
        opml += '  </head>\n'
        opml += '  <body>\n'

        # Track unique categories
        categories = {}

        # First pass: organize feeds by category
        for feed in feeds:
            feed_categories = feed[2].split(',') if feed[2] else ['Uncategorized']
            for category in feed_categories:
                category = category.strip()
                if category not in categories:
                    categories[category] = []
                categories[category].append(feed)

        # Second pass: write feeds organized by category
        for category in sorted(categories.keys()):
            category = category.replace("&","&amp;")
            opml += f'    <outline text="{category}" title="{category}">\n'
            for feed in categories[category]:
                title = feed[0].replace('"', '&quot;')
                url = feed[1].replace('"', '&quot;')
                tags = feed[3] if feed[3] else ''
                title = title.replace("&","&amp;")
                opml += f'      <outline type="rss" text="{title}" title="{title}" xmlUrl="{url}"'
                if tags:
                    opml += f' category="{tags}"'
                opml += '/>\n'
            opml += '    </outline>\n'

        opml += '  </body>\n'
        opml += '</opml>'

        # Write to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"feedln-{timestamp}.opml"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(opml)

        footerpop(stdscr, f"Feeds exported to {filename}")
        log_event(f"Feeds exported to OPML file: {filename}")

    except Exception as e:
        footerpop(stdscr, f"Error exporting OPML: {str(e)}", 1)
        log_event(f"Error exporting OPML: {str(e)}")


# Load feeds from CSV into database
def load_feeds_to_db(csv_file, conn):
    cursor = conn.cursor()
    with open(csv_file, mode="r") as file:
        reader = csv.DictReader(file)
        for row in reader:
            # Skip empty lines or lines starting with '#'
            if not row:
                continue

            if row['Name'].startswith('#'):
                continue
            else:
                try:
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO feeds (name, url, tags)
                        VALUES (?, ?, ?)
                        """,
                        (row["Name"], row["URL"], row.get("Tags", ""))
                    )
                    feed_id = cursor.lastrowid  # Get the last inserted feed ID

                    # Handle multiple categories, split by ';'
                    category_field = row.get("Category")  # Get the Category field
                    if category_field:  # Check if the field is not None or empty
                        categories = category_field.split(";")  # Split categories by semicolon
                        for category in categories:
                            category = category.strip()  # Remove whitespace
                            cursor.execute(
                                """
                                INSERT OR IGNORE INTO categories (name)
                                VALUES (?)
                                """,
                                (category,)
                            )
                            cursor.execute(
                                """
                                INSERT OR IGNORE INTO feed_categories (feed_id, category_id)
                                SELECT ?, id FROM categories WHERE name = ?
                                """,
                                (feed_id, category)
                            )
                except sqlite3.IntegrityError as e:
                    print(f"Skipping duplicate feed: {row['URL']} - {e}")
                    pass
    conn.commit()


# Fetch categories from database
def fetch_categories(conn, orderby=1):
    if orderby == 1:
        # Order by name
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT name, id 
            FROM categories 
            ORDER BY name ASC
        """)
    elif orderby == 2:
        # Order by id
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT name, id 
            FROM categories 
            ORDER BY id ASC
        """)
    elif orderby == 3:
        # Order by unread count
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.name, c.id, COUNT(CASE WHEN fi.is_read = 0 THEN 1 END) as unread_count
            FROM categories c
            LEFT JOIN feed_categories fc ON c.id = fc.category_id
            LEFT JOIN feeds f ON fc.feed_id = f.id
            LEFT JOIN feed_items fi ON f.id = fi.feed_id
            GROUP BY c.name, c.id
            ORDER BY unread_count DESC, c.name ASC
        """)

    categories = cursor.fetchall()
    # If using unread count query, strip the count from result
    # if orderby == 3:
    #    return [(category[0], category[1]) for category in categories]
    return [(category[0], category[1]) for category in categories]


# Fetch feeds by category
def fetch_feeds_by_category(conn, category, orderby='c.name'):
    forder = "c.name"
    if orderby == 1:
        forder = "f.name"
    elif orderby == 2:
        forder = "f.id"
    elif orderby == 3:
        forder = "f.url"
    elif orderby == 4:
        # Order by unread count
        cursor = conn.cursor()
        cursor.execute("""
            SELECT f.id, f.name AS feed_name, f.url, f.tags,
                   COUNT(CASE WHEN fi.is_read = 0 THEN 1 END) as unread_count
            FROM feeds f
            JOIN feed_categories fc ON f.id = fc.feed_id
            JOIN categories c ON fc.category_id = c.id
            LEFT JOIN feed_items fi ON f.id = fi.feed_id
            WHERE c.name = ?
            GROUP BY f.id, f.name, f.url, f.tags
            ORDER BY unread_count DESC
        """, (category,))
        feeds = cursor.fetchall()
        return feeds  # Return the list of feeds with unread counts

    # Original query for other sort orders
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT f.id, f.name AS feed_name, f.url, f.tags 
        FROM feeds f
        JOIN feed_categories fc ON f.id = fc.feed_id
        JOIN categories c ON fc.category_id = c.id
        WHERE c.name = ? 
        ORDER BY {forder} ASC
    """, (category,))
    feeds = cursor.fetchall()
    return feeds  # Return the list of feeds


# Fetch items for a feed
def fetch_feed_items(conn, feed_id,sort=1):
    #1 sort by date
    # 2 sort by title
    cursor = conn.cursor()
    if sort == 1:
        sql = "SELECT id, title, summary, is_read, last_updated, created, link FROM feed_items WHERE feed_id = ? ORDER BY last_updated DESC"
    elif sort == 2 :
        sql = "SELECT id, title, summary, is_read, last_updated, created, link FROM feed_items WHERE feed_id = ? ORDER BY title DESC"
    cursor.execute(
        sql , (feed_id,)
    )
    return cursor.fetchall()


# Update feed items in database
def update_feed_items(stdscr,conn, feed):
    global reqtimeout
    cursor = conn.cursor()
    try:
        response = requests.get(feed[2], timeout=reqtimeout)
        if response.status_code == 200:
            parsed_feed = feedparser.parse(response.content)  # Parse the content with feedparser
            for entry in parsed_feed.entries:
                updated_parsed = entry.get("updated_parsed")
                created_parsed = entry.get("created_parsed")

                timestamp_update = int(time.mktime(updated_parsed)) if updated_parsed else 0
                timestamp_create = int(time.mktime(created_parsed)) if created_parsed else 0
                content = entry.get("content", [{}])[0].get("value", "")
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO feed_items (feed_id, title, summary, content, last_updated, created, link)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (feed[0], entry.title, entry.summary, content, timestamp_update, timestamp_create, entry.link)
                )
        else:
            txt = f"Failed to retrieve: {feed[2]} Code:{response.status_code}"
            footerpop(stdscr,txt,1)
            log_event(txt) 
    except:
        txt = f"Timedout to retrieve: {feed[2]}"
        footerpop(stdscr,txt,1)
        log_event(txt) 
    
    conn.commit()
    
def get_feed_item_counts_by_category(conn, category):
    #print(category)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(fi.id) AS total_items, 
               SUM(CASE WHEN fi.is_read = 0 THEN 1 ELSE 0 END) AS total_unread
        FROM feed_items fi
        JOIN feeds f ON fi.feed_id = f.id
        WHERE f.id IN (SELECT feed_id FROM feed_categories WHERE category_id = ?)
    """, (category,))
    return cursor.fetchone()

def get_feed_item_counts_by_feed(conn, feed):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(fi.id) AS total_items, 
               SUM(CASE WHEN fi.is_read = 0 THEN 1 ELSE 0 END) AS total_unread
        FROM feed_items fi
        JOIN feeds f ON fi.feed_id = f.id
        WHERE f.id = ?
    """, (feed,))
    return cursor.fetchone()

def maxlength(stdscr):
    height, width = stdscr.getmaxyx()
    return width

def clear_feeds_not_in_csv(stdscr,conn, csv_file):
    if not confirm(stdscr,"Erase orphan feeds? Write 'yes' to confirm:"):
        return
    
    # Load feeds from CSV
    csv_feeds = set()
    with open(csv_file, mode="r") as file:
        reader = csv.DictReader(file)
        for row in reader:
            csv_feeds.add(row["URL"])  # Assuming URL is the unique identifier

    cursor = conn.cursor()
    # Fetch current feeds from the database
    cursor.execute("SELECT url FROM feeds")
    db_feeds = cursor.fetchall()

    # Identify feeds to delete
    feeds_to_delete = [feed[0] for feed in db_feeds if feed[0] not in csv_feeds]

    # Delete feeds not in CSV
    for url in feeds_to_delete:
        cursor.execute("DELETE FROM feeds WHERE url = ?", (url,))
    
    # Delete categories that have no feeds
    cursor.execute("DELETE FROM feeds WHERE category NOT IN (SELECT DISTINCT category FROM feeds)")
    
    conn.commit()

def update_feeds_by_category(conn, category,stdscr):
    feeds = fetch_feeds_by_category(conn, category)
    for i,feed in enumerate(feeds):
        text = f"{i+1:3}/{len(feeds):3}| {category:12}|{feed[2]:25}"
        footer(stdscr,text)
        stdscr.refresh()
        update_feed_items(stdscr,conn, feed)

# 0 Unread : 1 Read
def mark_all_items_as(conn, feed_id,mark):
    cursor = conn.cursor()
    cursor.execute("UPDATE feed_items SET is_read = ? WHERE feed_id = ?", (mark,feed_id,))
    conn.commit()

# 0 Unread : 1 Read
def mark_category_as(conn,category,stdscr,mark):
    feeds = fetch_feeds_by_category(conn, category)
    for feed in feeds:
        text = f"Marking: {feed[2]}"
        footer(stdscr,text)
        stdscr.refresh()
        mark_all_items_as(conn, feed[0],mark)

# Add a new feed to the CSV file
def add_new_feed(stdscr, conn):
    global feedfile
    """Add a new feed to the database and CSV file."""
    height, width = stdscr.getmaxyx()
    curses.echo()  # Enable echo for input
    curses.curs_set(1)  # Show cursor

    # Get feed name
    footer(stdscr, "Enter feed name: ", 3)
    stdscr.refresh()
    stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
    name = stdscr.getstr(height-1, 17).decode('utf-8')

    if not name:
        curses.noecho()
        curses.curs_set(0)
        stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
        footerpop(stdscr, f"Abort!", color=1)
        return False

    # Get feed URL
    footer(stdscr, "Enter feed URL: ", 3)
    stdscr.refresh()
    url = stdscr.getstr(height-1, 17).decode('utf-8')
    if not url:
        curses.noecho()
        curses.curs_set(0)
        stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
        footerpop(stdscr, f"Abort!", color=1)
        return False

    # Get feed category
    footer(stdscr, "Enter feed category: ", 3)
    stdscr.refresh()
    category = stdscr.getstr(height-1, 21).decode('utf-8')
    if not category:
        curses.noecho()
        curses.curs_set(0)
        stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
        footerpop(stdscr, f"Abort!", color=1)
        return False
    
    stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)

    try:
        # Add to CSV file
        with open(feedfile, mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([name, url, category, ""])
        footerpop(stdscr, "Feed added successfully!")
        log_event(f"New feed added: {name} ({url})")

        load_feeds_to_db(feedfile, conn)

    except Exception as e:
        footerpop(stdscr, f"Error adding feed: {str(e)}", 1)
        log_event(f"Error adding feed: {str(e)}")
        False

    curses.noecho()
    curses.curs_set(0)
    return True

# Function to display help information
def display_help_categories(stdscr):
    stdscr.clear()
    header(stdscr,"Key Shortcuts")
    help_text = (
        "Enter/Right: Select category\n"
        "ESC/Left: Back\n"
        "q: Quit\n"
        "a: Add new Feed\n"
        "f: Fetch One Category\n"
        "F: Fetch All Categories\n"
        "r: Mark Category as Read\n"
        "u: Mark Category as Unread\n"
        "o: Change Sort Order (Name, ID, Unread count)\n"
        "O: Export feeds to OPML file\n"
        "R: Mark All Categories as read\n"
        "U: Mark All Categories as unread\n"
        "e: Edit Feeds with text editor\n"
        "s: Speak Text Menu\n"
        "x: Stop Speaking\n"
        "/: Search Categories for Text\n"
        "l: Watch log file, if Exists, with External Editor\n"
        "!: Delete Database file. Reopen the Program!\n"
        "#: Clear Database from Feeds, that don't Exist in Feeds File\n"
        "TAB: Browse Category\n"
    )
    stdscr.addstr(1, 0, help_text)
    footer(stdscr,"Press a key to go back...")
    stdscr.refresh()
    stdscr.getch()  # Wait for user input before returning
    
def display_help_feed_items(stdscr):
    stdscr.clear()
    header(stdscr,"Key Shortcuts")
    help_text = (
        "\n"
        "Up / Down: Navigate categories\n"
        "Enter/Right: Select category\n"
        "ESC/Left: Back\n"
        "q: Quit\n"
        "r: Mark Feed as read\n"
        "u: Mark Feed as unread\n"
        "t: Sort by Title\n"
        "d: Sort by Date\n"
        "s: Speak Text Menu\n"
        "x: Stop Speaking\n"
        "PgDn: Scroll Down\n"
        "PgUp: Scroll Up\n"
        "h: Help\n"
    )
    stdscr.addstr(1, 0, help_text)
    footer(stdscr,"Press a key to go back...")
    stdscr.refresh()
    stdscr.getch()  # Wait for user input before returning

def display_help_entry(stdscr):
    stdscr.clear()
    header(stdscr,"Key Shortcuts")
    help_text = (
        "\n"
        "Up / Down: Navigate categories\n"
        "PgDn: Scroll Down\n"
        "PgUp: Scroll Up\n"
        "ESC/Left: Back\n"
        "q: Quit\n"
        "e: Export to text file\n"
        "o: Open Link in Browser\n"
        "1: Copy Title to clipboard\n"
        "2: Copy Link to clipboard\n"
        "3: Copy Summary to clipboard\n"
        "4: Copy Content to clipboard\n"
        "s: Speak Text Menu\n"
        "x: Stop Speaking\n"
        "h: Help\n"
    )
    stdscr.addstr(1, 0, help_text)
    footer(stdscr,"Press a key to go back...")
    stdscr.refresh()
    stdscr.getch()  # Wait for user input before returning

def display_help_feeds(stdscr):
    stdscr.clear()
    header(stdscr,"Key Shortcuts")
    help_text = (
        "\n"
        "Up / Down: Navigate categories\n"
        "Enter/Right: Select category\n"
        "ESC/Left: Back\n"
        "q: Quit\n"
        "f: Update Feed\n"
        "r: Mark Feed as read\n"
        "u: Mark Feed as unread\n"
        "o: Change Sort Order (Name, ID, Unread count...)\n"
        "s: Speak Text Menu\n"
        "x: Stop Speaking\n"
        "PgDn: Scroll Down\n"
        "PgUp: Scroll Up\n"
        "h: Help\n"
    )
    stdscr.addstr(1, 0, help_text)
    footer(stdscr,"Press a key to go back...")
    stdscr.refresh()
    stdscr.getch()  # Wait for user input before returning


def cat_order_to_string(i):
    if i == 1:
        return "Name"
    elif i == 2:
        return "ID"
    elif i == 3:
        return "Unread Count"

# Search a category and display feed items
def search_category(stdscr, conn, category):
    footer(stdscr, "Search in: [A]ll [T]itle [C]ontent [S]ummary [Q]uit", 3)
    stdscr.refresh()
    where_key = stdscr.getch()
    
    if where_key == ord("a"):
        search_where = 'all'
    elif where_key == ord("t"):
        search_where = 'title'
    elif where_key == ord("c"):
        search_where = 'content'
    elif where_key == ord("s"):
        search_where = 'summary'
    elif where_key == ord("q"):  # ESC
        return
    else:
        return
        
    # Get search text
    curses.echo()
    footer(stdscr, "Enter search text: ", 3)
    stdscr.refresh()
    stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
    search_text = stdscr.getstr(curses.LINES-1, 19).decode('utf-8')
    stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
    curses.noecho()
    
    if search_text:
        feed_items = get_feed_items_bycategory(conn, category, search_text, search_where)
        display_category_feed_items(stdscr, conn, category,search_text,search_where)


# Function to display categories
def display_categories(stdscr, conn):
    global feedfile, editor, xterm, logfile, FETCHONLOAD
    curses.curs_set(0)  # Disable cursor
    orderi = 3
    categories = fetch_categories(conn,orderi)

    current_category = 0
    start_index = 0  # Track the starting index for display

    if FETCHONLOAD:
        FETCHONLOAD = False
        for cat in categories:
            update_feeds_by_category(conn, cat[0], stdscr)

    while True:
        max_display = curses.LINES - 2  # Maximum number of categories to display
        stdscr.clear()
        header(stdscr, f"[] {program} v{version} [Sort by: {cat_order_to_string(orderi)}]")

        # Display categories within the current view
        for i in range(start_index, min(start_index + max_display, len(categories))):
            total = get_feed_item_counts_by_category(conn, categories[i][1])
            
            #print(total)
            #stdscr.getch()
            
            all_items = total[0] if total and total[0] is not None else 0  # Default to 0 if None
            unread = total[1] if total and total[1] is not None else 0  # Default to 0 if None
            line = f"> {unread:5} | {all_items:5} | {categories[i][0]}" if i == current_category else f"  {unread:5} | {all_items:5} | {categories[i][0]}"
            if unread > 0:
                stdscr.addstr(i - start_index + 1, 0, line, curses.color_pair(1) | curses.A_BOLD)
            else:
                stdscr.addstr(i - start_index + 1, 0, line, curses.color_pair(1))

        footer(stdscr, "q:quit | Enter:Select | ESC:Back | h:Help | PgUp,PgDn:Scroll")
        stdscr.refresh()

        key = stdscr.getch()

        if key == curses.KEY_UP and current_category > 0:
            current_category -= 1
            if current_category < start_index:  # Adjust start_index if needed
                start_index = max(0, start_index - 1)
        elif key == curses.KEY_DOWN and current_category < len(categories) - 1:
            current_category += 1
            if current_category >= start_index + max_display:  # Adjust start_index if needed
                start_index += 1
        elif key == curses.KEY_PPAGE:  # Page Up
            if start_index > 0:
                start_index = max(0, start_index - max_display)
                current_category = max(0, current_category - max_display)
            else:
                current_category = 0
        elif key == curses.KEY_NPAGE:  # Page Down
            if start_index + max_display < len(categories):
                start_index += max_display
                current_category = min(len(categories) - 1, current_category + max_display)
            else:
                current_category = len(categories) - 1  # Scroll to the end    
        elif key == curses.KEY_HOME:  # Home key
            current_category = 0  # Scroll to the start
            start_index = 0  # Reset start index
        elif key == curses.KEY_END:  # End key
            current_category = len(categories) - 1  # Scroll to the end
            start_index = max(0, len(categories) - max_display)
        elif key == ord("\n") or key == curses.KEY_RIGHT:  # Enter key
            display_feeds(stdscr, conn, categories[current_category][0])
        elif key == 9:  # TAB Key
            display_category_feed_items(stdscr, conn, categories[current_category][0])
        elif key == ord("/"):
            search_category(stdscr, conn, categories[current_category][0])
        elif key == ord("f"):  # Fetch one category
            update_feeds_by_category(conn, categories[current_category][0], stdscr)
        elif key == ord("F"):  # Update All Categories
            for cat in categories:
                update_feeds_by_category(conn, cat[0], stdscr)
        elif key == ord("q") or key == curses.KEY_LEFT or key == 27:
            break
        elif key == ord("a"):
            if add_new_feed(stdscr, conn):
                categories = fetch_categories(conn,orderi)
                current_category = 0
                start_index = 0
        elif key == ord("r"):  # Mark Category as read
            mark_category_as(conn, categories[current_category][0], stdscr, 1)
        elif key == ord("u"):  # Mark Category as unread
            mark_category_as(conn, categories[current_category][0], stdscr, 0)
        elif key == ord("R"):  # Mark All Categories as read
            for cat in categories:
                mark_category_as(conn, cat[0], stdscr, 1)
        elif key == ord("U"):  # Mark All Categories as unread
            for cat in categories:
                mark_category_as(conn, cat[0], stdscr, 0)
        elif key == ord("h"):  # Help key
            display_help_categories(stdscr)
        elif key == ord("!"):
            delete_database_file(stdscr)
        elif key == ord("%"):
            clean_database(stdscr)
        elif key == ord("#"):
            clear_feeds_not_in_csv(stdscr,conn,feedfile)
        elif key == ord("e"):
            os.system(f"xterm {xterm} -e {editor} {feedfile}")
        elif key == ord("l"):
            os.system(f"xterm {xterm} -e {editor} {logfile}")
        elif key == ord("o"):
            orderi += 1
            if orderi > 3: orderi = 1
            categories = fetch_categories(conn,orderi)
        elif key == ord("x"):
            tts.stop()
        elif key == ord("s"): 
            height, width = stdscr.getmaxyx()
            stdscr.addstr(height-1, 0, str("Speak: [T]itle [C]ancel").ljust(width-1), curses.color_pair(4) | curses.A_BOLD)
            key = stdscr.getch()
            if key == ord("t"):
                tts.speak(categories[current_category][0])
            elif key == ord("c"):
                pass
        elif key == ord("O"):  # Capital O for OPML export
            export_opml(stdscr, conn)

def header(stdscr,text):
    global database
    height, width = stdscr.getmaxyx()
    db_size = f"DB:{format_file_size(os.path.getsize(database))}"
    stdscr.addstr(0,0," "*(width-1), curses.color_pair(2) | curses.A_BOLD)
    stdscr.addstr(0, 0, text[:width-1], curses.color_pair(2) | curses.A_BOLD)
    stdscr.addstr(0,width-len(db_size)-1,db_size, curses.color_pair(2) | curses.A_BOLD)

def footer(stdscr,text,error=0):
    height, width = stdscr.getmaxyx()
    color = 0
    if error == 0:
        color = curses.color_pair(2) | curses.A_BOLD
    elif error == 3:
        color = curses.color_pair(4) | curses.A_BOLD
    else:
        color = curses.color_pair(3) | curses.A_BOLD
    stdscr.addstr(height-1,0," "*(width-1), color)
    stdscr.addstr(height-1,0,text[:width-1], color)
    
  
# Function to format file size from bytes to a human-readable format
def format_file_size(size_in_bytes):
    if size_in_bytes < 1024:
        return f"{size_in_bytes} Bytes"
    elif size_in_bytes < 1024 ** 2:
        return f"{size_in_bytes / 1024:.2f} KB"
    elif size_in_bytes < 1024 ** 3:
        return f"{size_in_bytes / (1024 ** 2):.2f} MB"
    else:
        return f"{size_in_bytes / (1024 ** 3):.2f} GB"

def feed_order_to_string(i):
    if i == 1:
        return "By Name"
    elif i == 2:
        return "By ID"
    elif i == 3:
        return "By URL"
    elif i == 4:
        return "By Unread Count"

# Function to display feeds within a category
def display_feeds(stdscr, conn, category):
    orderi = 4
    feeds = fetch_feeds_by_category(conn, category,orderi)
    current_feed = 0
    start_index = 0  # Track the starting index for display
    max_display = curses.LINES - 2  # Maximum number of items to display

    while True:
        stdscr.clear()
        header(stdscr, f": {category} [Sort: {feed_order_to_string(orderi)}]")

        # Display the feeds with pagination
        for i in range(start_index, min(start_index + max_display, len(feeds))):
            total_items, total_unread = get_feed_item_counts_by_feed(conn, feeds[i][0])
            total_items = total_items if total_items is not None else 0
            total_unread = total_unread if total_unread is not None else 0
            
            text = f" {total_unread:5} | {total_items:5} | {feeds[i][1]}"
            if i == current_feed:
                text = ">" + text
            else:
                text = " " + text
            if total_unread > 0:
                stdscr.addstr(i - start_index + 1, 0, text, curses.color_pair(1) | curses.A_BOLD)
            else:
                stdscr.addstr(i - start_index + 1, 0, text, curses.color_pair(1))

        footer(stdscr, "q:quit | Enter:Select | ESC:Back | h:Help | PgUp,PgDn:Scroll")
        stdscr.refresh()

        key = stdscr.getch()

        if key == curses.KEY_UP and current_feed > 0:
            current_feed -= 1
            if current_feed < start_index:  # Adjust start_index if needed
                start_index = max(0, start_index - 1)
        elif key == curses.KEY_DOWN and current_feed < len(feeds) - 1:
            current_feed += 1
            if current_feed >= start_index + max_display:  # Adjust start_index if needed
                start_index += 1
        elif key == curses.KEY_HOME:  # Home key
            current_feed = 0  # Scroll to the start
            start_index = 0  # Reset start index
        elif key == curses.KEY_END:  # End key
            current_feed = len(feeds) - 1  # Scroll to the end
            start_index = max(0, len(feeds) - max_display)
        elif key == curses.KEY_PPAGE:  # Page Up
            if start_index > 0:
                start_index = max(0, start_index - max_display)
                current_feed = max(0, current_feed - max_display)
            else:
                current_feed = 0
        elif key == curses.KEY_NPAGE:  # Page Down
            if start_index + max_display < len(feeds):
                start_index += max_display
                current_feed = min(len(feeds) - 1, current_feed + max_display)
            else:
                current_feed = len(feeds) - 1  # Scroll to the end
        elif key == ord("\n") or key == curses.KEY_RIGHT:  # Enter key
            #print(feeds[current_feed])
            #stdscr.getch()
            display_feed_items(stdscr, conn, feeds[current_feed], category)
        elif key == ord('f'):
            footer(stdscr, "Fetching Feed...")
            update_feed_items(stdscr,conn, feeds[current_feed])
        elif key == 27 or key == curses.KEY_LEFT:  # ESC key
            break
        elif key == ord("q") or key == 27:
            exit(0)
        elif key == ord("o"):
            orderi += 1
            if orderi > 4: orderi = 1
            feeds = fetch_feeds_by_category(conn, category, orderi)
            current_feed = 0
        elif key == ord("h"):
            display_help_feeds(stdscr)
        elif key == ord("r"):
            mark_all_items_as(conn, feeds[current_feed][0],1)
        elif key == ord("u"):
            mark_all_items_as(conn, feeds[current_feed][0],0)
        elif key == ord("x"):
            tts.stop()
        elif key == ord("s"):
            height, width = stdscr.getmaxyx()
            stdscr.addstr(height-1, 0, str("Speak: [T]itle [C]ancel").ljust(width-1), curses.color_pair(4) | curses.A_BOLD)
            key = stdscr.getch()
            if key == ord("t"):
                tts.speak(feeds[current_feed][1])
            elif key == ord("c"):
                pass

# Function to display feed items
def display_feed_items(stdscr, conn, feed,category=""):
    feed_items = fetch_feed_items(conn, feed[0])
    current_item = 0
    start_index = 0  # Track the starting index for display

    #stdscr.move(0,0)
    #print(feed_items[1])
    #print(f"--- {len(feed_items[1])}")
    #key = stdscr.getch()
    
    while True:
        stdscr.clear()
        unread_count = sum(1 for item in feed_items if not item[3])  # Count unread items
        header(stdscr, f": {category} : {feed[1]} [Unread : {unread_count}]")
        max_display = curses.LINES - 2  # Maximum number of items to display
        max_length = maxlength(stdscr) - 1  # Leave space for cursor
       
        # Display the feed items with proper length handling
        if feed_items:
            for i in range(start_index, min(start_index + max_display, len(feed_items))):
                title = feed_items[i][1][:max_length - 3]  # Reserve space for status
                last_updated = time.strftime('%Y-%m-%d', time.localtime(feed_items[i][4]))  # Format last updated timestamp
                display_str = f"> {last_updated} | {title}" if i == current_item else f"  {last_updated} | {title}"
                try:
                    if feed_items[i][3]==1:
                        stdscr.addstr(i - start_index + 1, 0, display_str[:max_length-2],curses.color_pair(1))  
                    else:
                        stdscr.addstr(i - start_index + 1, 0, display_str[:max_length-2],curses.color_pair(1)|curses.A_BOLD)  
                except:
                    stdscr.addstr(i - start_index + 1, 0, f"Error {feed_items[i][2]}")  
        
        footer(stdscr, "q:quit | Enter:Select | ESC:Back | h:help")
        stdscr.refresh()

        key = stdscr.getch()

        if key == curses.KEY_UP and current_item > 0:
            current_item -= 1
            if current_item < start_index:  # Adjust start_index if needed
                start_index = max(0, start_index - 1)
        elif key == curses.KEY_DOWN and current_item < len(feed_items) - 1:
            current_item += 1
            if current_item >= start_index + max_display:  # Adjust start_index if needed
                start_index += 1
        elif key == curses.KEY_PPAGE:  # Page Up
            if start_index > 0:
                start_index = max(0, start_index - max_display)
                current_item = max(0, current_item - max_display)
            else:
                current_item = 0
        elif key == curses.KEY_NPAGE:  # Page Down
            if start_index + max_display < len(feed_items):
                start_index += max_display
                current_item = min(len(feed_items) - 1, current_item + max_display)
            else:
                current_item = min(len(feed_items) - 1, current_item + max_display)
        elif key == ord("\n") or key == curses.KEY_RIGHT:  # Enter key
            if len(feed_items) > 0:
                mark_item_as_read(conn, feed_items[current_item][0])
                display_feed_entry(stdscr, conn, feed_items[current_item])
                feed_items = fetch_feed_items(conn, feed[0])
        elif key == 27 or key == curses.KEY_LEFT:  # ESC key
            break
        elif key == ord("q"):
            exit(0)
        elif key == ord("d"):
            feed_items = fetch_feed_items(conn, feed[0])
        elif key == ord("t"):
            feed_items = fetch_feed_items(conn, feed[0], 2)
        elif key == ord("r"):  # Mark Category as read
            mark_item_as_read(conn, feed_items[current_item][0])
            feed_items = fetch_feed_items(conn, feed[0])
        elif key == ord("u"):  # Mark Category as unread
            mark_item_as_read(conn, feed_items[current_item][0],0)
            feed_items = fetch_feed_items(conn, feed[0])
        elif key == ord("h"):
            display_help_feed_items(stdscr)
        elif key == curses.KEY_HOME:  # Home key
            current_item = 0  # Scroll to the start
            start_index = 0  # Reset start index
        elif key == curses.KEY_END:  # End key
            current_item = len(feed_items) - 1  # Scroll to the end
            start_index = max(0, len(feed_items) - max_display)  # Adjust start index if needed
        elif key == ord("x"):
            tts.stop()
        elif key == ord("s"):
            height, width = stdscr.getmaxyx()
            stdscr.addstr(height-1, 0, str("Speak: [T]itle c[A]tegory [C]ancel").ljust(width-1), curses.color_pair(4) | curses.A_BOLD)
            key = stdscr.getch()
            if key == ord("t"):
                tts.speak(feed_items[current_item][1])
            elif key == ord("a"):
                tts.speak(feed[1])
            elif key == ord("c"):
                pass


def get_feed_items_bycategory(conn, category, search_text=None, search_where='all'):
    """
    Get feed items by category with optional search functionality
    Parameters:
        conn: Database connection
        category: Category name to filter by
        search_text: Optional text to search for
        search_where: Where to search ('all', 'title', 'content', 'summary')
    Returns:
        List of feed items matching the criteria
    """
    cursor = conn.cursor()
    
    # Base SQL query
    sql = """SELECT fi.id, fi.title, fi.summary, fi.is_read, fi.last_updated, fi.created, fi.link,
             f.name as feed_name
             FROM feed_items fi
             JOIN feeds f ON fi.feed_id = f.id
             JOIN feed_categories fc ON f.id = fc.feed_id
             JOIN categories c ON fc.category_id = c.id
             WHERE c.name = ?"""
    
    params = [category]
    
    # Add search conditions if search_text is provided
    if search_text:
        search_text = f"%{search_text}%"  # Add wildcards for LIKE query
        if search_where == 'title':
            sql += " AND fi.title LIKE ?"
            params.append(search_text)
        elif search_where == 'content':
            sql += " AND fi.content LIKE ?"
            params.append(search_text)
        elif search_where == 'summary':
            sql += " AND fi.summary LIKE ?"
            params.append(search_text)
        else:  # 'all' - search in title, content, and summary
            sql += """ AND (
                fi.title LIKE ? OR 
                fi.content LIKE ? OR 
                fi.summary LIKE ?
            )"""
            params.extend([search_text] * 3)
    
    # Add ordering
    sql += " ORDER BY fi.last_updated DESC"
    
    cursor.execute(sql, params)
    return cursor.fetchall()

# Display Feed items by category
def display_category_feed_items(stdscr, conn, category="", search_text=None, search_where='all'):
    feed_items = get_feed_items_bycategory(conn,category, search_text,search_where)
    current_item = 0
    start_index = 0  # Track the starting index for display
    
    while True:
        stdscr.clear()
        unread_count = sum(1 for item in feed_items if not item[3])  # Count unread items
        header(stdscr, f": {category} [Unread : {unread_count}]")
        #header(stdscr, f": {category} : {feed[1]} [Unread : {unread_count}]")
        max_display = curses.LINES - 2  # Maximum number of items to display
        max_length = maxlength(stdscr) - 1  # Leave space for cursor
       
        # Display the feed items with proper length handling
        if feed_items:
            for i in range(start_index, min(start_index + max_display, len(feed_items))):
                title = feed_items[i][1][:max_length - 20]  # Reserve space for status
                feedname = feed_items[i][7][:15]
                last_updated = time.strftime('%Y-%m-%d', time.localtime(feed_items[i][4]))  # Format last updated timestamp
                display_str = f"> {last_updated} | {feedname:15} | {title}" if i == current_item else f"  {last_updated} | {feedname:15} | {title}"
                try:
                    if feed_items[i][3]==1:
                        stdscr.addstr(i - start_index + 1, 0, display_str[:max_length-2],curses.color_pair(1))  
                    else:
                        stdscr.addstr(i - start_index + 1, 0, display_str[:max_length-2],curses.color_pair(1)|curses.A_BOLD)  
                except:
                    stdscr.addstr(i - start_index + 1, 0, f"Error {feed_items[i][2]}")  
        
        footer(stdscr, "q:quit | Enter:Select | ESC:Back | h:help")
        stdscr.refresh()

        key = stdscr.getch()

        if key == curses.KEY_UP and current_item > 0:
            current_item -= 1
            if current_item < start_index:  # Adjust start_index if needed
                start_index = max(0, start_index - 1)
        elif key == curses.KEY_DOWN and current_item < len(feed_items) - 1:
            current_item += 1
            if current_item >= start_index + max_display:  # Adjust start_index if needed
                start_index += 1
        elif key == curses.KEY_PPAGE:  # Page Up
            if start_index > 0:
                start_index = max(0, start_index - max_display)
                current_item = max(0, current_item - max_display)
            else:
                current_item = 0
        elif key == curses.KEY_NPAGE:  # Page Down
            if start_index + max_display < len(feed_items):
                start_index += max_display
                current_item = min(len(feed_items) - 1, current_item + max_display)
            else:
                current_item = min(len(feed_items) - 1, current_item + max_display)
        elif key == ord("\n") or key == curses.KEY_RIGHT:  # Enter key
            if len(feed_items) > 0:
                mark_item_as_read(conn, feed_items[current_item][0])
                display_feed_entry(stdscr, conn, feed_items[current_item])
                feed_items = get_feed_items_bycategory(conn,category,search_text,search_where)
        elif key == 27 or key == curses.KEY_LEFT:  # ESC key
            break
        elif key == ord("q"):
            exit(0)
        elif key == ord("r"):  # Mark Category as read
            mark_item_as_read(conn, feed_items[current_item][0])
            feed_items = get_feed_items_bycategory(conn,category,search_text,search_where)
        elif key == ord("u"):  # Mark Category as unread
            mark_item_as_read(conn, feed_items[current_item][0],0)
            feed_items = get_feed_items_bycategory(conn,category,search_text,search_where)
        elif key == ord("h"):
            display_help_feed_items(stdscr)
        elif key == curses.KEY_HOME:  # Home key
            current_item = 0  # Scroll to the start
            start_index = 0  # Reset start index
        elif key == curses.KEY_END:  # End key
            current_item = len(feed_items) - 1  # Scroll to the end
            start_index = max(0, len(feed_items) - max_display)  # Adjust start index if needed        
        elif key == ord("x"):
            tts.stop()
        elif key == ord("s"): 
            height, width = stdscr.getmaxyx()
            stdscr.addstr(height-1, 0, str("Speak: [T]itle [C]ancel").ljust(width-1), curses.color_pair(4) | curses.A_BOLD)
            key = stdscr.getch()
            if key == ord("t"):
                tts.speak(feed_items[current_item][1])
            elif key == ord("c"):
                pass

# Function to mark an item as read
def mark_item_as_read(conn, item_id,read=1):
    cursor = conn.cursor()
    cursor.execute("UPDATE feed_items SET is_read = ? WHERE id = ?", (read,item_id,))
    conn.commit()

# Function to display a single feed entry
def display_feed_entry(stdscr, conn, feed_item):
    global browser,media,xterm
    cursor = conn.cursor()
    cursor.execute("SELECT title, summary, content, last_updated FROM feed_items WHERE id = ?", (feed_item[0],))
    title, summary, content, last_updated = cursor.fetchone()

    if not content:
        content = summary
    # Format the date
    formatted_date = time.strftime('%Y-%m-%d', time.localtime(last_updated))
    # Assuming the link is stored in the feed_item, you may need to adjust this based on your actual data structure
    link = feed_item[6]  # Adjust this if the link is stored differently

    soup = BeautifulSoup(content, "html.parser")
    
    # Replace <br> with new lines and <p> with double new lines for paragraphs
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all("p"):
        p.insert_before("\n")
        p.insert_after("\n")
    for p in soup.find_all("pre"):
        p.insert_before("\n")
        p.insert_after("\n")
    for p in soup.find_all("code"):
        p.insert_before("[")
        p.insert_after("]")

    # Get the plain text while preserving whitespace
    plain_text = soup.get_text()

    # Wrap the text to fit the terminal width
    max_length = maxlength(stdscr) - 1  # Leave space for cursor

    wrapped_lines = []

    lines = plain_text.splitlines()  # Split the text into lines
    for line in lines:
        if len(line)>max_length-1:
            l = wrap(line,max_length-1, drop_whitespace=False, tabsize=4)
            wrapped_lines.extend(l)
        else:
            wrapped_lines.append(line)

    current_line_index = 0
    num_lines = len(wrapped_lines)

    while True:
        stdscr.clear()
        max_length = maxlength(stdscr) - 1
        stdscr.addstr(0, 0, f"Title:")
        stdscr.addstr(0, max_length-28, f"Date:")
        stdscr.addstr(1, 0, f"{title[:max_length]}", curses.A_BOLD)
        stdscr.addstr(2, 0, f"<{link[:max_length-2]}>")
        stdscr.addstr(0, max_length-22, f"{time.strftime('%Y-%m-%d / %H:%M:%S', time.localtime(last_updated))}", curses.A_BOLD)
        stdscr.addstr(3, 0, "-"*max_length)

        # Display the wrapped lines with scrolling
        for i in range(current_line_index, min(current_line_index + curses.LINES - 5, num_lines)):
            stdscr.addstr(i - current_line_index + 4, 0, wrapped_lines[i])

        footer(stdscr, f"Esc/Left:Back | q:quit | h:help")
        stdscr.refresh()

        key = stdscr.getch()

        if key == curses.KEY_UP and current_line_index > 0:
            current_line_index -= 1
        elif key == curses.KEY_DOWN and current_line_index < num_lines - (curses.LINES - 5):
            current_line_index += 1
        elif key == curses.KEY_PPAGE and current_line_index > 0:  # Page Up
            current_line_index = max(0, current_line_index - (curses.LINES - 5))  # Scroll up by one page
        elif key == curses.KEY_NPAGE and current_line_index < num_lines - (curses.LINES - 5):  # Page Down
            current_line_index = min(num_lines - (curses.LINES - 5), current_line_index + (curses.LINES - 5))  # Scroll down by one page
        elif key == 27 or key == curses.KEY_LEFT:  # ESC key
            break
        elif key == ord("h"):
            display_help_entry(stdscr)
        elif key == ord("q"):
            exit(0)
        elif key == ord("o"):
            if is_program_installed(browser):
                run_program(stdscr,f"{browser} {link}")
        elif key == ord("e"):
            fn = f"{time.strftime('%Y%m%d_%H%M%S')}_rss.txt"
            export_feed_entry_to_file(conn, feed_item, fn)
            footerpop(stdscr,f"Exported to: {fn}")
        elif key == curses.KEY_HOME:  # Home key
            current_line_index = 0  # Scroll to the start
        elif key == curses.KEY_END:  # End key
            current_line_index = num_lines - (curses.LINES - 5)  # Scroll to the end
        elif key == ord("l") or key == curses.KEY_RIGHT:
            display_links(stdscr, conn, feed_item)
        elif key == ord("1"):
            pyperclip.copy(title)
            footerpop(stdscr,"Title copied to clipboard")
        elif key == ord("2"):
            pyperclip.copy(link)
            footerpop(stdscr,"Link copied to clipboard")
        elif key == ord("3"):
            pyperclip.copy(summary)
            footerpop(stdscr,"Summary copied to clipboard")
        elif key == ord("4"):
            pyperclip.copy(content)
            footerpop(stdscr,"Content copied to clipboard")
        elif key == ord("x"):
            tts.stop()
        elif key == ord("s"):
            height, width = stdscr.getmaxyx()
            stdscr.addstr(height-1, 0, str("Speak: [T]itle [D]ate [B]ody [C]ancel").ljust(width-1), curses.color_pair(4) | curses.A_BOLD)
            key = stdscr.getch()
            if key == ord("t"):
                tts.speak(title)
            elif key == ord("d"):
                tts.speak(f"{time.strftime('%Y-%m-%d / %H:%M:%S', time.localtime(last_updated))}")
            elif key == ord("b"):
                tts.speak(SPEAK + ' "' + str(lines).strip())
            elif key == ord("c"):
                pass



def footerpop(stdscr,text,delay=2,color=3):
    footer(stdscr, text, color)
    stdscr.refresh()
    time.sleep(delay)  # Show feedback for a moment

def display_help_links(stdscr):
    stdscr.clear()
    header(stdscr,"Key Shortcuts")
    help_text = (
        "\n"
        "Up / Down: Navigate\n"
        "Enter/Right: Open with Browser\n"
        "ESC/Left: Back\n"
        "c: Copy URL to clipboard\n"
        "m: Open with Media Player\n"
        "q: Quit\n"
        "h: Help\n"
    )
    stdscr.addstr(1, 0, help_text)
    footer(stdscr,"Press a key to go back...")
    stdscr.refresh()
    stdscr.getch()  # Wait for user input before returning

def display_links(stdscr, conn, feed_item):
    cursor = conn.cursor()
    cursor.execute("SELECT summary, content FROM feed_items WHERE id = ?", (feed_item[0],))
    result = cursor.fetchone()
    summary = result[0] if result else None
    content = result[1] if result else None
    if not content:
        content = summary
    soup = BeautifulSoup(content, "html.parser")

    # Regular expression to find URLs
    url_pattern = r'(https?://[^\s]+)'
    found_links = re.findall(url_pattern, content)
    
    # Create a list of links and images
    links = [(a['href'], 'url') for a in soup.find_all('a', href=True)]
    images = [(img['src'], 'image') for img in soup.find_all('img', src=True)]
    links.append((feed_item[6], 'url'))  # Assuming feed_item[6] is the link
    
    # Add found links to the items
    items = []
    items.extend(links)
    items.extend(images)
    items.extend([(link, 'url') for link in found_links])  # Add found links

    
    current_item = 0
    start_index = 0  # Track the starting index for display

    while True:
        stdscr.clear()
        header(stdscr, "Links and Images")
        max_length = curses.COLS

        # Display the links and images with pagination
        max_display = curses.LINES - 2  # Maximum number of items to display
        for i in range(start_index, min(start_index + max_display, len(items))):
            tp = "'"
            if items[i][1] == 'url': 
                tp = "u"
            elif items[i][1] == "image":
                tp = 'i'
            display_str = f"{tp}: {items[i][0]}"
            if i == current_item:
                display_str = "> " + display_str[:max_length-4]
            else:
                display_str = "  " + display_str[:max_length-4]
            try:
                stdscr.addstr(i - start_index + 1, 0, display_str)
            except:
                print(f"{i - start_index + 1}")
                stdscr.getch()

        footer(stdscr, f"Esc/Left:Back | q:quit | Right:Open | h:help")
        stdscr.refresh()

        key = stdscr.getch()

        if key == curses.KEY_UP and current_item > 0:
            current_item -= 1
            if current_item < start_index:  # Adjust start_index if needed
                start_index = max(0, start_index - 1)
        elif key == curses.KEY_DOWN and current_item < len(items) - 1:
            current_item += 1
            if current_item >= start_index + max_display:  # Adjust start_index if needed
                start_index += 1
        elif key == curses.KEY_HOME:  # Home key
            current_item = 0  # Scroll to the start
            start_index = 0  # Reset start index
        elif key == curses.KEY_END:  # End key
            current_item = len(items) - 1  # Scroll to the end
            start_index = max(0, len(items) - max_display)
        elif key == ord("\n") or key == curses.KEY_RIGHT:  # Enter key
            run_program(stdscr, f"{browser} {items[current_item][0]}")
        elif key == ord("m"):
            footerpop(stdscr,"Opening media. Please wait...",1)
            run_program(stdscr, f"{media} {items[current_item][0]}")
        elif key == 27 or key == curses.KEY_LEFT:  # ESC key
            break
        elif key == ord("h"):
            display_help_links(stdscr)
        elif key == ord("q"):
            exit(0)
        elif key == ord("c"):  # Shortcut to copy link to clipboard
            pyperclip.copy(links[current_item][0])  # Copy the link to clipboard
            footerpop(stdscr, f"Copied to clipboard: {links[current_item][0]}")
            

def run_program(stdscr,param):
    try:
        os.system(param)
    except subprocess.CalledProcessError as e:
        footer(stdscr,"Error:\n", e.stderr)  # Print the error if the command fails

def export_feed_entry_to_file(conn, feed_item, filename):
    cursor = conn.cursor()
    cursor.execute("SELECT title, summary, content, last_updated FROM feed_items WHERE id = ?", (feed_item[0],))
    title, summary, content, last_updated = cursor.fetchone()

    # Format the date
    formatted_date = time.strftime('%Y-%m-%d', time.localtime(last_updated))

    # Prepare the content to write to the file
    export_content = f"Title: {title}\n"
    export_content += f"Date: {formatted_date}\n"
    export_content += f"Summary: {summary}\n"
    export_content += "-"*70 + "\n"
    export_content += f"Content:\n{content}\n"

    # Write to the specified file
    with open(filename, 'w', encoding='utf-8') as file:
        file.write(export_content)


def initialize_screen(stdscr, conn):
    curses.start_color()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)  # Color pair 1: White text on black background
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLUE)    # Color pair 2: Yellow text on blue background
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_RED)
    curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_GREEN)
    display_categories(stdscr, conn)  # Call the display function after initializing colors 


# Main function
def main():
    global feedfile, database, FETCHONLOAD
    args = parse_arguments()  # Parse command line arguments
    feedfile = args.file  # Update feedfile with command line argument if provided
    FETCHONLOAD = args.fetch
    database = os.path.splitext(feedfile)[0] + '.sq3'
    load_config()  # Load user defined variables
    check_feed_file()  # Check feed file, add default if not exist
    conn = setup_database()
    load_feeds_to_db(feedfile, conn)
    curses.wrapper(lambda stdscr: initialize_screen(stdscr, conn))


if __name__ == "__main__":
    tts = InterruptibleTTS()
    status = os.system(f"dpkg -s espeak > /dev/null 2>&1")
    if status == 0:
        tts.enabled = True
    main()
