import os
import re
import subprocess
import tempfile

from itertools import ifilter
from operator import attrgetter

from rbtools.api.client import RBClient
from twisted.internet import reactor

from helga import settings
from helga import log
from helga.plugins import command, ResponseNotReady


logger = log.getLogger(__name__)

_rb_host = settings.CODEREVIEW_REVIEWBOARD_API_URL.strip('/').replace('http://', '').replace('https://', '')
_cr_pat = re.compile(r'(https?://{0}/r/|cr)(\d+)'.format(_rb_host), re.I)

# Flake8 cmd
FLAKE8_BASE_CMD = [
    'flake8',
    '--max-complexity={0}'.format(getattr(settings, 'CODEREVIEW_FLAKE8_MAX_COMPLEXITY', -1)),
    '--max-line-length={0}'.format(getattr(settings, 'CODEREVIEW_FLAKE8_MAX_LINE_LENGTH', 79)),
]

if hasattr(settings, 'CODEREVIEW_FLAKE8_IGNORE'):
    FLAKE8_BASE_CMD.append('--ignore={0}'.format(settings.CODEREVIEW_FLAKE8_IGNORE))


@command('review', aliases=['codereview'],
         help="Provide insightful reviewboard comments. Usage: !review [cr####|<url>]")
def codereview(client, channel, nick, message, cmd, args):
    arglist = ' '.join(args)

    try:
        matches = map(lambda x: int(x[1]), _cr_pat.findall(arglist))
    except (IndexError, ValueError):
        return "Sorry, {0}, I can't understand these: {1}".format(nick, arglist)

    if not matches:
        return "You must tell me the reivew you would like me to process {0}".format(nick)

    client.msg(channel, "Ok, {0}, I'll get right on that".format(nick))
    reactor.callLater(1, process_review_requests, client, channel, nick, matches)
    raise ResponseNotReady


def process_review_requests(client, channel, nick, review_ids):
    """
    Processes a list of review request ids using a shared client
    """
    logger.info("Starting codereview of: {0}".format(review_ids))
    api = RBClient(settings.CODEREVIEW_REVIEWBOARD_API_URL,
                   username=settings.CODEREVIEW_REVIEWBOARD_API_USERNAME,
                   password=settings.CODEREVIEW_REVIEWBOARD_API_PASSWORD)

    try:
        api_root = api.get_root()
    except:
        logger.exception("Cannot access reviewboard")
        client.msg(
            channel,
            "I can't complete your review {0} because I can't access reviewboard".format(nick)
        )
        return

    errors = []

    for review_id in review_ids:
        try:
            do_review(client, channel, nick, api_root, review_id)
        except:
            logger.exception("Cannot codereview cr{0}".format(review_id))
            errors.append(review_id)

    if errors:
        cr_list = ', '.join(map(lambda id: 'cr{0}'.format(id), errors))
        client.msg(channel, 'Codereview complete {0}, but I was unable to review: {1}'.format(nick, cr_list))
    else:
        client.msg(channel, 'Codereview complete {0}'.format(nick))


def _is_python(diff_file):
    """
    Checks if a reviewboard review file is a python file by checking its extension
    """
    try:
        ext = os.path.splitext(diff_file.dest_file)[-1]
    except:
        return False
    return ext.lower() == '.py'


def _flake8(file):
    """
    Take one of reviewboard's file objects and run it through flake8 and return errors.
    Since the flake8 internals only print out the results, we need to write the file
    out to disk and run flake8 against that
    """
    _, filename = os.path.split(file.dest_file)
    diff_data = file.get_diff_data()

    # Write the file out and flake8 it
    with tempfile.NamedTemporaryFile(prefix=filename.replace(' ', '-'), suffix='.py') as tmp:
        tmp.write(file.get_patched_file().data)
        tmp.flush()

        proc = subprocess.Popen(FLAKE8_BASE_CMD + [tmp.name],
                                stdout=subprocess.PIPE,
                                stdin=subprocess.PIPE)

        stdout, _ = proc.communicate()

    # Convert flake8 output to a lineno -> msg mapping
    errors = []
    strict_codes = getattr(settings, 'CODEREVIEW_OPEN_ISSUE_CODES', [])

    for line in stdout.splitlines():
        location, _, msg = line.partition(' ')
        code = msg.partition(' ')[0]
        info = location.split(':')

        try:
            # The location bit is like <filename>:<lineno>:<colno>
            lineno, colno = int(info[1]), int(info[2])
        except ValueError:
            continue

        # Normalize the line number using the diff data
        # http://www.reviewboard.org/docs/manual/dev/webapi/2.0/resources/file-diff/
        for chunk in diff_data.chunks:
            for row in chunk.lines:
                if row[4] == lineno:
                    lineno = row[0]
                    break

        errors.append({
            'filediff_id': file.id,
            'first_line': lineno,
            'num_lines': 1,
            'text': 'Column {0}: {1}'.format(colno, msg),
            'issue_opened': code in strict_codes,
        })

    return errors


def do_review(client, channel, nick, api_root, review_id):
    """
    Code reivew a single review request. This retrievs the specified review
    request and runs flake8 against all python files that have updates. If no
    warnings are found, then YOU GO GLENN COCO. Otherwise, all errors, warnings,
    etc are shown in a reply
    """
    logger.info("Codereview on review request {0}".format(review_id))
    review_request = api_root.get_review_request(review_request_id=review_id)
    diff = sorted(review_request.get_diffs(), key=attrgetter('revision'))[-1]

    # FIXME: Check if we have already reviewed this diff

    # Get all the errors and what not for python files
    comments = []
    for file in ifilter(_is_python, diff.get_files()):
        try:
            comments.extend(_flake8(file))
        except:
            logger.exception('Cannot flake file: {0}'.format(file.dest_file))

    # Slice the list if we are worried about hard comment limits
    total_comments = len(comments)
    comments = comments[:getattr(settings, 'CODEREVIEW_COMMENT_LIMIT', len(comments))]

    # Thumbs up
    if not comments:
        logger.info("Review request {0} has linted cleanly".format(review_id))
        review_request.get_reviews().create(body_top='This code has passed flake8 checks. :)',
                                            public=True,
                                            ship_it=False)
        return

    if len(comments) < total_comments:
        extra = 'Showing first {0} errors'.format(len(comments))
    else:
        extra = 'See below'

    review = review_request.get_reviews().create(
        body_top='This code has not passed flake8 checks. {0}'.format(extra)
    )

    review_comments = review.get_diff_comments()

    # Post notices
    for comment in comments:
        review_comments.create(**comment)

    review.update(public=True)
