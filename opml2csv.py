#!/usr/bin/env python3
from lxml import etree as ET
import csv
import sys
import argparse

def opml_to_csv(opml_file, csv_file):
    """
    Convert OPML file to CSV format for Feedln.
    Extracts feed title, XML URL, and category from OPML outlines.
    """
    try:
        # Parse OPML file
        parser = ET.XMLParser(recover=True)
        tree = ET.parse(opml_file, parser)
        root = tree.getroot()
        
        # Open CSV file for writing
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # Write header
            writer.writerow(['Name', 'URL', 'Category', 'Tags'])
            
            # Find all outline elements (feeds)
            for outline in root.findall('.//outline'):
                # Check if it's a feed (has xmlUrl attribute)
                xml_url = outline.get('xmlUrl')
                if xml_url:
                    title = outline.get('title') or outline.get('text', '')
                    # Get the category by looking at parent outline's text/title
                    category = ''
                    parent = outline.getparent()
                    if parent is not None and parent.tag == 'outline':
                        category = parent.get('text') or parent.get('title', '')
                    writer.writerow([title, xml_url, category])
        
        print(f"Successfully converted {opml_file} to {csv_file}")
        
    except ET.ParseError:
        print(f"Error: Could not parse {opml_file}. Make sure it's a valid OPML file.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Convert OPML file to CSV format for Feedln')
    parser.add_argument('opml_file', help='Input OPML file')
    parser.add_argument('-o', '--output', help='Output CSV file (default: output.csv)',
                      default='output.csv')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Convert OPML to CSV
    opml_to_csv(args.opml_file, args.output)

if __name__ == '__main__':
    main()
