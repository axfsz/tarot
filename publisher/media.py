"""Prepare a job's pictures/video for upload.

- Xiaohongshu image notes: every picture is fitted onto a 3:4 (1080x1440) canvas.
- WeChat Channels / TikTok need a video: pictures become a short 9:16 slideshow
  (with a silent audio track, which both platforms expect).
"""
import os, subprocess, shutil, tempfile
from pathlib import Path

DATA = Path(os.getenv('DATA_DIR', '/data'))
APP_ROOT = Path(os.getenv('APP_ROOT', Path(__file__).resolve().parent.parent))
BG = '0x1d1a2b'
IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp'}
VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.webm'}


class MediaError(Exception):
    pass


def resolve(item):
    rel = str(item.get('file', ''))
    if not rel or '..' in rel.split('/') or rel.startswith('/'):
        raise MediaError('bad media path')
    if rel.startswith('static/'):
        base = APP_ROOT
    elif rel.startswith('media/'):
        base = DATA
    else:
        raise MediaError('bad media path')
    p = (base / rel).resolve()
    if not str(p).startswith(str(base.resolve())) or not p.is_file():
        raise MediaError('media file missing: ' + rel)
    return p


def ffmpeg(*args):
    exe = shutil.which('ffmpeg')
    if not exe:
        raise MediaError('ffmpeg is not installed in the publisher image')
    r = subprocess.run([exe, '-hide_banner', '-loglevel', 'error', '-y', *args], capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise MediaError('ffmpeg failed: ' + r.stderr[-300:])


def fit(src, dst, w, h):
    ffmpeg('-i', str(src), '-vf', f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={BG},setsar=1',
           '-frames:v', '1', '-q:v', '2', str(dst))


def slideshow(images, dst, w=1080, h=1920):
    per = 6.0 if len(images) == 1 else 3.5
    args = []
    for im in images:
        args += ['-loop', '1', '-t', str(per), '-i', str(im)]
    args += ['-f', 'lavfi', '-t', str(per * len(images)), '-i', 'anullsrc=r=44100:cl=stereo']
    chains = [f'[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={BG},setsar=1,fps=30,'
              f'fade=t=in:st=0:d=0.4,fade=t=out:st={per - 0.4}:d=0.4[v{i}]' for i in range(len(images))]
    graph = ';'.join(chains) + ';' + ''.join(f'[v{i}]' for i in range(len(images))) + f'concat=n={len(images)}:v=1:a=0[v]'
    ffmpeg(*args, '-filter_complex', graph, '-map', '[v]', '-map', f'{len(images)}:a', '-shortest',
           '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', str(dst))


def prepare(platform, media, needs, max_images=9):
    """Returns (kind, [files], tmpdir). kind is 'images' or 'video'."""
    paths = [resolve(m) for m in media or []]
    videos = [p for p in paths if p.suffix.lower() in VIDEO_EXT]
    images = [p for p in paths if p.suffix.lower() in IMAGE_EXT][:max_images]
    if not videos and not images:
        raise MediaError('no picture or video attached')
    tmp = Path(tempfile.mkdtemp(prefix='pub-'))
    if videos:
        return 'video', [videos[0]], tmp
    if needs == 'video':
        out = tmp / 'slideshow.mp4'
        slideshow(images, out)
        return 'video', [out], tmp
    files = []
    for i, im in enumerate(images):
        out = tmp / f'{i:02d}.jpg'
        fit(im, out, 1080, 1440)
        files.append(out)
    return 'images', files, tmp
