import os
import sys
import requests
import json
import browser_cookie3
import argparse
from mutagen.id3 import ID3, TIT2, TALB, TPE1, TRCK, ID3NoHeaderError, APIC
import zipfile
import shutil

GLOBAL_TRACK_NUMBER = 1

def parse_entries(entries, subchapters, numbering_prefix=''):
    for entry in entries:
        id_ = entry.get('id')
        title = entry.get('title')
        numbering = entry.get('numbering', numbering_prefix)
        full_numbering = numbering_prefix if numbering == None else numbering
        if 'entries' in entry:
            # Recursively parse child entries
            new_prefix = full_numbering if full_numbering else numbering_prefix
            parse_entries(entry['entries'], subchapters, numbering_prefix=new_prefix)
        else:
            if id_ and title:
                subchapters.append({
                    'id': id_,
                    'title': title,
                    'numbering': full_numbering,
                })

def get_image(image_path, session):
    if image_path:
        if image_path.startswith('http'):
            try:
                resp = session.get(image_path)
                if resp.status_code == 200:
                    print(f"Downloaded image from {image_path}")
                    image = resp.content
                else:
                    print(f"Failed to download image from {image_path}. Status code: {resp.status_code}")
                    image = None
            except Exception as e:
                print(f"Failed to download image from {image_path}. Error: {e}")
                image = None
        else:
            try:
                with open(image_path, 'rb') as f:
                    image = f.read()
                print(f"Loaded image from {image_path}")
            except Exception as e:
                print(f"Failed to load image from {image_path}. Error: {e}")
                image = None
    else:
        image = None

def get_metdata(url, session):
    if url.startswith('http'):
        try:
            resp = session.get(url)
            if resp.status_code == 200:
                data = resp.json()
                print(f"Loaded metadata from {url}")
            else:
                print(f"Failed to load metadata from {url}. Status code: {resp.status_code}")
                exit(1)
        except Exception as e:
            print(f"Failed to load metadata from {url}. Error: {e}")
            exit(1)
    else:
        try:
            with open(url, 'r') as f:
                data = json.load(f)
            print(f"Loaded metadata from {url}")
        except Exception as e:
            print(f"Failed to load metadata from {url}. Error: {e}")
            exit(1)
    return data


def download_audio(subchapters, output_folder, session, base_url, lecture_title, image_path=None):
    image = get_image(image_path, session)
    for sub in subchapters:
        global GLOBAL_TRACK_NUMBER
        audio_id = sub['id']
        title = sub['title']
        numbering = sub['numbering'].strip() if sub['numbering'] else ''
        url = base_url.format(audio_id)
        # Prepare filename
        if numbering:
            filename = f'{GLOBAL_TRACK_NUMBER}-{numbering}-{title.replace(" ", "_")}.mp3'
        else:
            filename = f'{title}.mp3'
        # Make filename safe
        safe_filename = ''.join(c for c in filename if c.isalnum() or c in ' ._-').rstrip()
        # Define full path
        full_path = os.path.join(output_folder, safe_filename)
        # Download the file
        print(f"Downloading: {url}")
        try:
            resp = session.get(url)
            if resp.status_code == 200:
                with open(full_path, 'wb') as f:
                    f.write(resp.content)
                print(f"Saved: {full_path}")
                add_id3_tags(full_path, title=title, lecture_title=lecture_title, numbering=numbering, image=image)
            else:
                print(f"Failed to download {url}. Status code: {resp.status_code}")
        except Exception as e:
            print(f"Failed to download {url}. Error: {e}")
        GLOBAL_TRACK_NUMBER += 1

def add_id3_tags(file_path, title, lecture_title, numbering='', image=None):    
    try:
        audio = ID3(file_path)
    except ID3NoHeaderError:
        audio = ID3()

    if image:
        audio['APIC'] = APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=image)

    audio['TALB'] = TALB(encoding=3, text=lecture_title)
    audio['TIT2'] = TIT2(encoding=3, text=f'{numbering} - {title}')
    
    
    audio['TRCK'] = TRCK(encoding=3, text=str(GLOBAL_TRACK_NUMBER))
    audio.save(file_path)
    print(f"Added ID3 tags to {file_path}\n")

def zip_audio_files(output_folder, lecture_title):
    """Zip all mp3 files in output folder into a zip named after the lecture."""
    if not lecture_title:
        lecture_title = "lecture"
    
    # Create safe filename for zip
    safe_title = ''.join(c for c in lecture_title if c.isalnum() or c in ' ._-').rstrip()
    zip_name = f"{safe_title}.zip"
    
    # Create zip file
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(output_folder):
            for file in files:
                if file.endswith('.mp3'):
                    file_path = os.path.join(root, file)
                    arcname = os.path.basename(file_path)
                    zipf.write(file_path, arcname)
    
    print(f"\nCreated zip archive: {zip_name}")
    return zip_name

def main():
    parser = argparse.ArgumentParser(description='Download lectures.')
    parser.add_argument('metadata', type=str, help='Path to the metadata JSON file')
    parser.add_argument('--output-folder', type=str, default='./audio', help='Output folder for downloaded files')
    parser.add_argument('--zip', action='store_true', 
                       help='Create zip archive of downloaded files')
    parser.add_argument('--img',type=str, help='Path to the image file for cover art')
    args = parser.parse_args()

    try:
        cj = browser_cookie3.firefox(domain_name='iu.org')
    except Exception as e:
        print(f"Could not load cookies: {e}")
        sys.exit(1)

    session = requests.Session()
    session.cookies = cj

    data = get_metdata(args.metadata, session)

    bookId = data.get('bookId')
    if not bookId:
        print("bookId not found in JSON")
        sys.exit(1)

    subchapters = []

    # Start parsing from the 'content' section
    content = data.get('tableOfContents', {}).get('content', {})
    sections = content.get('sections', [])
    lecture_title = data.get('title')

    for section in sections:
        numbering = section.get('numbering')
        numbering_prefix = numbering if numbering else ''
        parse_entries([section], subchapters, numbering_prefix=numbering_prefix)

    output_folder = args.output_folder
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)


    base_url = f'https://idss-assets.iu.org/audio/{bookId}/{{}}.mp3'
    download_audio(subchapters, output_folder, session, base_url, lecture_title, image_path=args.img)

    if args.zip:
        zip_name = zip_audio_files(output_folder, lecture_title)
        # Optional: remove the temp folder after zipping
        shutil.rmtree(output_folder)

if __name__ == '__main__':
    main()