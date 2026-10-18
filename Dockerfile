FROM nvitaterna/wreckfest2-docker-server:console

# Install Xvfb and gosu for headless display and passwordless user switching
USER root
RUN apt-get update && apt-get install -y xvfb gosu && rm -rf /var/lib/apt/lists/*

# Pre-create log subdirectories and set ownership (though volumes will override, this ensures permissions)
RUN mkdir -p /home/steam/logs/wine /home/steam/logs/x /home/steam/logs/wf && chown -R steam:steam /home/steam/logs

# Hardened entrypoint: fixes bind-mount ownership, starts Xvfb, bounded window wait
COPY entry.sh /home/steam/entry.sh
RUN chmod +x /home/steam/entry.sh && chown steam:steam /home/steam/entry.sh

# Do NOT switch to USER steam here—the entrypoint runs as root, then drops via gosu
