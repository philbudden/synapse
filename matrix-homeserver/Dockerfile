FROM matrixdotorg/synapse:latest

# Add a small entrypoint that generates /data/homeserver.yaml on first run
# and patches a few safe defaults for local use.
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
