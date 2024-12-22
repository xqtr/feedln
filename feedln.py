#!/usr/bin/python3
import curses
import csv
import feedparser
import sqlite3
#from collections import defaultdict
import time
from bs4 import BeautifulSoup
import os
import subprocess
import pyperclip
import configparser
from textwrap import wrap
import re

program = "Feedln"
version = "1.0.0"
database = "feedln.sq3"
feedfile = "feedln.csv"
cfgfile = "feedln.cfg"

browser = "firefox"
media = "mpv"
xterm = "-fa 'Monospace' -fs 14"
editor = "nano"

def load_config():
    global media, xterm, editor
    config_file = cfgfile  # Assuming cfgfile is the path to your config file
    if os.path.exists(config_file):
        config = configparser.ConfigParser()
        config.read(config_file)
        if 'Settings' in config:
            media = config['Settings'].get('media', media)
            browser = config['Settings'].get('browser', browser)
            xterm = config['Settings'].get('xterm', xterm)
            editor = config['Settings'].get('editor', editor)

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
            category TEXT,
            tags TEXT
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

    if confirmation.lower() == 'yes':
        return True
    else:
        return False

def delete_database_file(stdscr):
    global database
    if confirm(stdscr,"Delete database? Write 'yes' to confirm:"):
        try:
            os.remove(database)
            footer(stdscr,f"Database file '{database}' has been deleted.")
            stdscr.refresh()
            time.sleep(1)
        except Exception as e:
            footer(stdscr,f"Error: {e}",1)
            stdscr.refresh()
            time.sleep(2)
    else:
        footerpop(stdscr,"Deletion canceled.")
    curses.curs_set(0)

# Load feeds from CSV into database
def load_feeds_to_db(csv_file, conn):
    cursor = conn.cursor()
    with open(csv_file, mode="r") as file:
        reader = csv.DictReader(file)
        for row in reader:
            try:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO feeds (name, url, category, tags)
                    VALUES (?, ?, ?, ?)
                    """,
                    (row["Name"], row["URL"], row.get("Category", "Uncategorized"), row.get("Tags", ""))
                )
            except sqlite3.IntegrityError as e:
                print(f"Skipping duplicate feed: {row['URL']} - {e}")
    conn.commit()

# Fetch categories from database
def fetch_categories(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT category FROM feeds")
    return [row[0] for row in cursor.fetchall()]

# Fetch feeds by category
def fetch_feeds_by_category(conn, category,order=1):
    orderby=""
    if order == 1: 
        orderby = "name"
    elif order == 2: 
        orderby = "id"
    elif order == 3:
        orderby = "url"

    cursor = conn.cursor()
    cursor.execute(f"SELECT id, name, url, tags FROM feeds WHERE category = ? ORDER BY {orderby} ASC", (category,))
    return cursor.fetchall()

# Fetch items for a feed
def fetch_feed_items(conn, feed_id,sort=1):
    #1 sort by date
    #2 sort by title
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
def update_feed_items(conn, feed):
    cursor = conn.cursor()
    parsed_feed = feedparser.parse(feed[2])
    for entry in parsed_feed.entries:
        #print(entry.get("link"))
        #print(entry.get("comments"))
        #print(entry.get("published"))
        #print(entry.get("author"))
        #print(entry.get("post-id"))
        #print(entry.published_parsed)
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
    conn.commit()
    
def get_feed_item_counts_by_category(conn, category):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(fi.id) AS total_items, 
               SUM(CASE WHEN fi.is_read = 0 THEN 1 ELSE 0 END) AS total_unread
        FROM feed_items fi
        JOIN feeds f ON fi.feed_id = f.id
        WHERE f.category = ?
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
    for feed in feeds:
        text = f"Updating: {feed[2]}"
        footer(stdscr,text)
        time.sleep(0.3)
        stdscr.refresh()
        update_feed_items(conn, feed)

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
        time.sleep(0.3)
        stdscr.refresh()
        mark_all_items_as(conn, feed[0],mark)

# Function to display help information
def display_help_categories(stdscr):
    stdscr.clear()
    header(stdscr,"Key Shortcuts")
    help_text = (
        "\n"
        "Up / Down: Navigate categories\n"
        "Enter/Left: Select category\n"
        "ESC: Back\n"
        "q: Quit\n"
        "f: Fetch one category\n"
        "F: Fetch All Categories\n"
        "r: Mark Category as read\n"
        "u: Mark Category as unread\n"
        "R: Mark All Categories as read\n"
        "U: Mark All Categories as unread\n"
        "e: Edit feeds with text editor\n"
        "!: Delete database file. Reopen the program!"
        "#: Clear database from feeds, that don't exist in feeds file\n"
        "h: Help\n"
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
        "o: Change Sort Order\n"
        "PgDn: Scroll Down\n"
        "PgUp: Scroll Up\n"
        "h: Help\n"
    )
    stdscr.addstr(1, 0, help_text)
    footer(stdscr,"Press a key to go back...")
    stdscr.refresh()
    stdscr.getch()  # Wait for user input before returning

# Function to display categories
def display_categories(stdscr, conn):
    global feedfile,editor,xterm
    curses.curs_set(0)  # Disable cursor
    categories = fetch_categories(conn)
    current_category = 0
    start_index = 0  # Track the starting index for display

    while True:
        max_display = curses.LINES - 2  # Maximum number of categories to display
        stdscr.clear()
        header(stdscr, f"[] {program} v{version}")

        # Display categories within the current view
        for i in range(start_index, min(start_index + max_display, len(categories))):
            total = get_feed_item_counts_by_category(conn, categories[i])
            all = total[0]
            unread = 0 if total[1] is None else total[1]
            line = f"> {unread:3} | {all:3} | {categories[i]}" if i == current_category else f"  {unread:3} | {all:3} | {categories[i]}"
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
        elif key == curses.KEY_NPAGE:  # Page Down
            if start_index + max_display < len(categories):
                start_index += max_display
                current_category = min(len(categories) - 1, current_category + max_display)
        elif key == curses.KEY_HOME:  # Home key
            current_category = 0  # Scroll to the start
            start_index = 0  # Reset start index
        elif key == curses.KEY_END:  # End key
            current_category = len(categories) - 1  # Scroll to the end
            start_index = max(0, len(categories) - max_display)
        elif key == ord("\n") or key == curses.KEY_RIGHT:  # Enter key
            display_feeds(stdscr, conn, categories[current_category])
        elif key == ord("f"):  # Fetch one category
            update_feeds_by_category(conn, categories[current_category], stdscr)
        elif key == ord("F"):  # Update All Categories
            for cat in categories:
                update_feeds_by_category(conn, cat, stdscr)
        elif key == ord("q") or key == curses.KEY_LEFT:
            break
        elif key == ord("r"):  # Mark Category as read
            mark_category_as(conn, categories[current_category], stdscr, 1)
        elif key == ord("u"):  # Mark Category as unread
            mark_category_as(conn, categories[current_category], stdscr, 0)
        elif key == ord("R"):  # Mark All Categories as read
            for cat in categories:
                mark_category_as(conn, cat, stdscr, 1)
        elif key == ord("U"):  # Mark All Categories as unread
            for cat in categories:
                mark_category_as(conn, cat, stdscr, 0)
        elif key == ord("h"):  # Help key
            display_help_categories(stdscr)
        elif key == ord("!"):
            delete_database_file(stdscr)
        elif key == ord("#"):
            clear_feeds_not_in_csv(stdscr,conn,feedfile)
        elif key == ord("e"):
            os.system(f"xterm {xterm} -e {editor} {feedfile}")

def header(stdscr,text):
    height, width = stdscr.getmaxyx()
    stdscr.addstr(0,0," "*(width-1), curses.color_pair(2) | curses.A_BOLD)
    stdscr.addstr(0, 0, text[:width-1], curses.color_pair(2) | curses.A_BOLD)

def footer(stdscr,text,error=0):
    global database
    height, width = stdscr.getmaxyx()
    db_size = f"DB:{format_file_size(os.path.getsize(database))}"
    color = 0
    if error == 0:
        color = curses.color_pair(2) | curses.A_BOLD
    elif error == 3:
        color = curses.color_pair(4) | curses.A_BOLD
    else:
        color = curses.color_pair(3) | curses.A_BOLD
    stdscr.addstr(height-1,0," "*(width-1), color)
    stdscr.addstr(height-1,0,text[:width-1], color)
    stdscr.addstr(height-1,width-len(db_size)-1,db_size, color)
  
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


# Function to display feeds within a category
def display_feeds(stdscr, conn, category):
    orderi = 1
    feeds = fetch_feeds_by_category(conn, category)
    current_feed = 0
    start_index = 0  # Track the starting index for display
    max_display = curses.LINES - 2  # Maximum number of items to display

    while True:
        stdscr.clear()
        header(stdscr, f": {category}")

        # Display the feeds with pagination
        for i in range(start_index, min(start_index + max_display, len(feeds))):
            total_items, total_unread = get_feed_item_counts_by_feed(conn, feeds[i][0])
            total_items = total_items if total_items is not None else 0
            total_unread = total_unread if total_unread is not None else 0
            
            text = f" {total_unread:3} | {total_items:3} | {feeds[i][1]}"
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
        elif key == curses.KEY_NPAGE:  # Page Down
            if start_index + max_display < len(feeds):
                start_index += max_display
                current_feed = min(len(feeds) - 1, current_feed + max_display)
        elif key == ord("\n") or key == curses.KEY_RIGHT:  # Enter key
            #print(feeds[current_feed])
            #stdscr.getch()
            display_feed_items(stdscr, conn, feeds[current_feed], category)
        elif key == ord('f'):
            footer(stdscr, "Fetching Feed...")
            update_feed_items(conn, feeds[current_feed])
        elif key == 27 or key == curses.KEY_LEFT:  # ESC key
            break
        elif key == ord("q"):
            exit(0)
        elif key == ord("o"):
            orderi += 1
            if orderi > 3: orderi = 1
            feeds = fetch_feeds_by_category(conn, category, orderi)
            current_feed = 0
        elif key == ord("h"):
            display_help_feeds(stdscr)
        elif key == ord("r"):
            mark_all_items_as(conn, feeds[current_feed][0],1)
        elif key == ord("u"):
            mark_all_items_as(conn, feeds[current_feed][0],0)

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
        elif key == curses.KEY_NPAGE:  # Page Down
            if start_index + max_display < len(feed_items):
                start_index += max_display
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
    max_length = curses.COLS - 1  # Leave space for cursor
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
        max_length = curses.COLS - 1
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


def footerpop(stdscr,text,delay=2):
    footer(stdscr, text, 3)
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


def initialize_colors(stdscr, conn):
    curses.start_color()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)  # Color pair 1: White text on black background
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLUE)    # Color pair 2: Yellow text on blue background
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_RED)
    curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_GREEN)
    display_categories(stdscr, conn)  # Call the display function after initializing colors 

# Main function
def main():
    global feedfile
    load_config() # Load user defined variables
    check_feed_file() # Check feed file, add default if not exist
    conn = setup_database()
    csv_file = feedfile  # Path to your CSV file
    load_feeds_to_db(csv_file, conn)
    curses.wrapper(lambda stdscr: initialize_colors(stdscr, conn))

if __name__ == "__main__":
    main()
