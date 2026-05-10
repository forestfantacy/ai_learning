#!/usr/bin/env python3
"""
RSS Feed 抓取和解析脚本
Usage: python3 fetch_rss.py <url> [--output json|md]
"""

import sys
import json
import argparse
import xml.etree.ElementTree as ET
from urllib.request import urlopen
from urllib.parse import urlparse

def fetch_rss(url):
    """Fetch and parse RSS feed."""
    try:
        with urlopen(url, timeout=30) as response:
            content = response.read()
    except Exception as e:
        print(f"Error fetching RSS: {e}", file=sys.stderr)
        sys.exit(1)
        
    root = ET.fromstring(content)
    
    # Handle RSS 2.0 and Atom formats
    items = []
    
    if root.tag == 'rss' or root.tag.endswith('rss'):
        # RSS 2.0 format
        channel = root.find('channel')
        if channel is not None:
            for item in channel.findall('item'):
                entry = {
                    'title': get_text(item, 'title'),
                    'link': get_text(item, 'link'),
                    'description': get_text(item, 'description'),
                    'pub_date': get_text(item, 'pubDate'),
                }
                items.append(entry)
    elif root.tag.endswith('feed'):
        # Atom format
        for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
            item = {
                'title': get_atom_text(entry, 'title'),
                'link': get_atom_link(entry),
                'description': get_atom_text(entry, 'summary') or get_atom_text(entry, 'content'),
                'pub_date': get_atom_text(entry, 'updated') or get_atom_text(entry, 'published'),
            }
            items.append(item)
            
    return items

def get_text(parent, tag):
    elem = parent.find(tag)
    return elem.text if elem is not None else ''

def get_atom_text(parent, tag):
    ns = '{http://www.w3.org/2005/Atom}'
    elem = parent.find(f'{ns}{tag}')
    return elem.text if elem is not None else ''

def get_atom_link(parent):
    ns = '{http://www.w3.org/2005/Atom}'
    link = parent.find(f'{ns}link')
    if link is not None:
        return link.get('href', '')
    return ''

def output_json(items):
    print(json.dumps(items, indent=2, ensure_ascii=False))

def output_markdown(items, source_url):
    domain = urlparse(source_url).netloc
    print(f"# RSS Feed: {domain}\n")
    for i, item in enumerate(items[:20], 1):  # Limit to 20 items
        print(f"## {i}. {item['title']}")
        print(f"- **Link**: {item['link']}")
        if item.get('pub_date'):
            print(f"- **Published**: {item['pub_date']}")
        if item.get('description'):
            desc = item['description'][:200] + '...' if len(item['description']) > 200 else item['description']
            print(f"- **Summary**: {desc}")
        print()

def main():
    parser = argparse.ArgumentParser(description='Fetch and parse RSS feed')
    parser.add_argument('url', help='RSS feed URL')
    parser.add_argument('--output', '-o', choices=['json', 'md'], default='md',
                       help='Output format (default: md)')
    args = parser.parse_args()
    
    items = fetch_rss(args.url)
    
    if args.output == 'json':
        output_json(items)
    else:
        output_markdown(items, args.url)

if __name__ == '__main__':
    main()
