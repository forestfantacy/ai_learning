#!/usr/bin/env python3
"""
GitHub Trending 数据抓取和解析脚本
Usage: python3 fetch_github_trending.py [--output json|md]
"""

import re
import sys
import json
import argparse
from urllib.request import urlopen
from html.parser import HTMLParser

class GitHubTrendingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.repos = []
        self.current_repo = {}
        self.in_article = False
        self.in_link = False
        self.in_desc = False
        self.in_lang = False
        self.in_stars = False
        self.expecting_repo_name = False
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        
        # Find repo article blocks
        if tag == 'article' and attrs_dict.get('class', '').startswith('Box-row'):
            self.in_article = True
            self.current_repo = {}
            
        # Find repo link (h2 > a)
        if self.in_article and tag == 'a' and 'href' in attrs_dict:
            href = attrs_dict['href']
            if href.startswith('/') and '/' in href[1:] and not self.current_repo.get('name'):
                self.current_repo['name'] = href[1:]  # Remove leading /
                self.current_repo['url'] = f"https://github.com{href}"
                
        # Find description
        if self.in_article and tag == 'p' and attrs_dict.get('class', '') == 'col-9 color-fg-muted my-1 pr-4':
            self.in_desc = True
            
        # Find language
        if self.in_article and tag == 'span' and attrs_dict.get('itemprop', '') == 'programmingLanguage':
            self.in_lang = True
            
        # Find star count
        if self.in_article and tag == 'a' and attrs_dict.get('class', '').startswith('Link Link--muted'):
            if 'stargazers' in attrs_dict.get('href', ''):
                self.in_stars = True
                
    def handle_data(self, data):
        if self.in_desc:
            self.current_repo['description'] = data.strip()
            self.in_desc = False
        elif self.in_lang:
            self.current_repo['language'] = data.strip()
            self.in_lang = False
        elif self.in_stars:
            self.current_repo['stars'] = data.strip()
            self.in_stars = False
            
    def handle_endtag(self, tag):
        if tag == 'article' and self.in_article:
            if self.current_repo.get('name'):
                self.repos.append(self.current_repo)
            self.current_repo = {}
            self.in_article = False

def fetch_trending():
    """Fetch GitHub Trending page and parse repos."""
    url = "https://github.com/trending"
    try:
        with urlopen(url, timeout=30) as response:
            html = response.read().decode('utf-8')
    except Exception as e:
        print(f"Error fetching trending page: {e}", file=sys.stderr)
        sys.exit(1)
        
    parser = GitHubTrendingParser()
    parser.feed(html)
    return parser.repos

def output_json(repos):
    print(json.dumps(repos, indent=2, ensure_ascii=False))

def output_markdown(repos):
    print("# GitHub Trending\n")
    for i, repo in enumerate(repos, 1):
        print(f"## {i}. {repo['name']}")
        print(f"- **URL**: {repo['url']}")
        print(f"- **Language**: {repo.get('language', 'N/A')}")
        print(f"- **Stars**: {repo.get('stars', 'N/A')}")
        print(f"- **Description**: {repo.get('description', 'N/A')}\n")

def main():
    parser = argparse.ArgumentParser(description='Fetch GitHub Trending repositories')
    parser.add_argument('--output', '-o', choices=['json', 'md'], default='md',
                       help='Output format (default: md)')
    args = parser.parse_args()
    
    repos = fetch_trending()
    
    if args.output == 'json':
        output_json(repos)
    else:
        output_markdown(repos)

if __name__ == '__main__':
    main()
