From ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && \
    apt install -y python3 python3-pip python3-dev bluez bluez-tools dbus libbluetooth-dev libdbus-glib-1-dev libdbus-1-dev python3-gi && \
    mkdir -p /root/.config/ntfy

WORKDIR /root
COPY tvcom/serial_lookup.py tvcom/serial_lookup.py
COPY simple-agent.py bluezutils.py restate.py magic.py requirements.txt entrypoint.sh .
COPY config/ntfy.yml .config/ntfy/

RUN python3 -m pip install -r requirements.txt

CMD ./entrypoint.sh



