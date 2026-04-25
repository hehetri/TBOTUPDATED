def is_admin(client):
    return client['character']['position'] == 1


def get_announce_text(message):
    return message[len('! '):].strip()