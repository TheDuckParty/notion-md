#!/usr/bin/env python3
import argparse
import json
import os
from functools import partial
from multiprocessing import Pool
from urllib.parse import urlparse, parse_qs

import requests


# PaperMod don't show image's caption
def get_image(block, args):
    url = block["content"]["file"]["url"]
    filename = f"{block['id']}.{url.split('/')[-1].split('?')[0].split('.')[-1]}"
    image_data = requests.get(url).content
    with open(f"{args.static}/{filename}", "wb") as file:
        file.write(image_data)
    image_path = os.path.join(args.url, filename)
    return f"![]({image_path}#center)"


def get_video(block, args):
    if "file" not in block["content"] or "url" not in block["content"]["file"]:
        return ""

    url = block["content"]["file"]["url"]
    filename = f"{block['id']}.{url.split('/')[-1].split('?')[0].split('.')[-1]}"
    video_static_path = os.path.join(args.static, filename)

    if not os.path.exists(video_static_path):
        print(f"Downloading video: {filename}")
        video_data = requests.get(url).content
        with open(video_static_path, "wb") as file:
            file.write(video_data)

    video_public_url = os.path.join(args.url, filename)

    return f'<video controls width="100%"><source src="{video_public_url}"></video>'


def get_embed(block):
    url = block["content"]["url"]

    if "youtube.com" in url or "youtu.be" in url:
        parsed_url = urlparse(url)
        if parsed_url.hostname == 'youtu.be':
            video_id = parsed_url.path[1:]
        else:
            video_id = parse_qs(parsed_url.query).get('v', [None])[0]

        if video_id:
            return f"{{{{< youtube {video_id} >}}}}"

    return f'<iframe src="{url}" width="100%" height="480" frameborder="0" allowfullscreen></iframe>'


def parse_annotations(annotations, text):
    if annotations["code"]:
        text = f"`{text}`"
    if annotations["bold"]:
        text = f"**{text}**"
    if annotations["italic"]:
        text = f"*{text}*"
    if annotations["strikethrough"]:
        text = f"~~{text}~~"
    if annotations["underline"]:
        text = f"<u>{text}</u>"
    if "background" in annotations["color"]:
        text = f"<mark>{text}</mark>"
    return text


def parse_block_type(block, numbered_list_index, depth, args):
    if block["type"] == "divider":
        return "---"
    if block["type"] == "image":
        return get_image(block, args)
    if block["type"] == "video":
        return get_video(block, args)
    if block["type"] == "embed":
        return get_embed(block)

    if "rich_text" not in block["content"] or not block["content"]["rich_text"]:
        return ""

    result = ""
    for rich_text in block["content"]["rich_text"]:
        text = parse_annotations(rich_text["annotations"], rich_text["plain_text"])
        if rich_text["href"]:
            text = f"[{text}]({rich_text['href']})"
        result += text
    if result:
        if block["type"] == "heading_1":
            result = f"# {result}"
        elif block["type"] == "heading_2":
            result = f"## {result}"
        elif block["type"] == "heading_3":
            result = f"### {result}"
        elif block["type"] == "code":
            result = f"```{block['content']['language']}\n{result}\n```"
        elif block["type"] == "bulleted_list_item":
            result = f"- {result}"
        elif block["type"] == "numbered_list_item":
            result = f"{numbered_list_index}. {result}"
        elif block["type"] == "to_do":
            if block["content"]["checked"]:
                result = f"- [x] {result}"
            else:
                result = f"- [ ] {result}"
        if block["type"] == "quote":
            result = f"> {result}"
        result = "\t" * depth + result
    return result


def render_page(blocks, depth, args):
    page = ""
    numbered_list_index = 0
    for block in blocks:
        if block["type"] == "numbered_list_item":
            numbered_list_index += 1
        else:
            numbered_list_index = 0
        text = parse_block_type(block, numbered_list_index, depth, args)
        if text:
            page += f"\n\n{text}"
        if block["children"]:
            page += render_page(block["children"], depth + 1, args)
    return page


def query_blocks(page_id, headers, start_cursor=None, blocks=None):
    if blocks:
        result = blocks
    else:
        result = []
    if start_cursor:
        url = f"https://api.notion.com/v1/blocks/{page_id}/children?start_cursor={start_cursor}"
    else:
        url = f"https://api.notion.com/v1/blocks/{page_id}/children"

    response = requests.get(url, headers=headers).json()

    for item in response["results"]:
        children = []
        if item["has_children"]:
            children = query_blocks(item["id"], headers)
        result.append({
            "id": item["id"],
            "type": item["type"],
            "content": item[item["type"]],
            "children": children
        })
    if response["has_more"]:
        result = query_blocks(page_id, headers, response["next_cursor"], result)
    return result


def parse_frontmatter(properties):
    return json.dumps({
        "categories": [item["name"] for item in properties["Categories"]["multi_select"]],
        "date": properties["Date"]["date"]["start"],
        "tags": [item["name"] for item in properties["Tags"]["multi_select"]],
        "title": properties["Title"]["title"][0]["plain_text"],
        "url": properties["URL"]["url"],
        "summary": properties["Summary"]["rich_text"][0]["plain_text"] if properties["Summary"]["rich_text"] else ""
    })


def query_db(db_id):
    result = {}
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    response = requests.post(url, headers=headers).json()
    for item in response["results"]:
        if args.hugo:
            if item["properties"]["Published"]["checkbox"]:
                result[item["id"]] = parse_frontmatter(item["properties"])
        else :
            result[item["id"]] = ""
    while response["has_more"]:
        data = {"start_cursor": response["next_cursor"]}
        response = requests.post(url, headers=headers, data=data).json()
        for item in response["results"]:
            if args.hugo:
                if item["properties"]["Published"]["checkbox"]:
                    result[item["id"]] = parse_frontmatter(item["properties"])
            else :
                result[item["id"]] = ""
    return result


def multi_thread(page_items, headers, args):
    page_id = page_items[0]
    frontmatter = page_items[1]
    blocks = query_blocks(page_id, headers)
    content = render_page(blocks, 0, args)
    with open(f"{args.content}/{page_id}.md", "w") as file:
        file.write(frontmatter)
        file.write(content)


def valid_dir(target):
    if os.path.exists(target):
        return target
    raise argparse.ArgumentTypeError(f"The directory '{target}' does not exist")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get Notion pages from specified database and convert it to Markdown")

    parser.add_argument("--static", type=valid_dir, help="static path folder", required=True)
    parser.add_argument("--url", type=str, help="URL for static files", required=True)
    parser.add_argument("--content", type=valid_dir, help="content path folder", required=True)
    parser.add_argument("--db", type=str, help="database ID", required=True)
    parser.add_argument("--key", type=str, help="Notion API key", required=True)
    parser.add_argument("--hugo", action=argparse.BooleanOptionalAction, help="add page front matter for Hugo")

    args = parser.parse_args()

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "Notion-Version": "2022-06-28",
        "Authorization": f"Bearer {args.key}"
    }

    pages = query_db(args.db)

    thread = min(os.cpu_count(), 3)

    task_function = partial(multi_thread, headers=headers, args=args)

    with Pool(thread) as p:
        p.map(task_function, pages.items())
