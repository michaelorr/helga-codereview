from helga.plugins import command


@command('review', help="Provide insightful reviewboard comments. Usage: !review [cr####|<url>]")
def review(client, channel, nick, message, cmd, args):
    pass
