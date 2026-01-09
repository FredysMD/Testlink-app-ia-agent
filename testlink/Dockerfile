FROM chusiang/testlink:latest

# Install PHP XML extension
RUN apt-get update && \
    apt-get install -y php7.0-xml && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Restart PHP-FPM to load the extension
RUN service php7.0-fpm restart || true