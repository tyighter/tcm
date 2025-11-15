ARG PYVERSION=3.11

# Create pipenv image to convert Pipfile to requirements.txt
FROM python:${PYVERSION}-slim as pipenv

# Copy Pipfile and Pipfile.lock
COPY Pipfile Pipfile.lock ./

# Install pipenv and convert to requirements.txt
RUN pip3 install --no-cache-dir --upgrade pipenv; \
    pipenv requirements > requirements.txt

FROM python:${PYVERSION}-slim as python-reqs

# Copy requirements.txt from pipenv stage
COPY --from=pipenv /requirements.txt requirements.txt

# Install build dependencies and python packages required by TCM
RUN apt-get update; \
    apt-get install -y --no-install-recommends gcc; \
    pip3 install --no-cache-dir -r requirements.txt; \
    apt-get purge -y --auto-remove gcc; \
    rm -rf /var/lib/apt/lists/*

# Set base image for running TCM
FROM python:${PYVERSION}-slim
LABEL maintainer="CollinHeist" \
      description="Automated title card maker for Plex"

# Set working directory, copy source into container
WORKDIR /maker
COPY . /maker

# Copy python packages from python-reqs
COPY --from=python-reqs /usr/local /usr/local

# Script environment variables
ENV TCM_PREFERENCES=/config/preferences.yml \
    TCM_IS_DOCKER=TRUE

# Delete setup files
# Create user and group to run the container
# Install imagemagick
# Clean up apt cache
# Override default ImageMagick policy XML file
RUN set -eux; \
    rm -f Pipfile Pipfile.lock; \
    groupadd -g 99 titlecardmaker; \
    useradd -u 100 -g 99 titlecardmaker; \
    apt-get update; \
    apt-get install -y --no-install-recommends imagemagick; \
    for package in libmagickcore-6.q16-8-extra \
                   libmagickcore-6.q16-7-extra \
                   libmagickcore-6.q16-6-extra; do \
        if apt-cache show "${package}" > /dev/null 2>&1; then \
            apt-get install -y --no-install-recommends "${package}"; \
            break; \
        fi; \
    done; \
    rm -rf /var/lib/apt/lists/*; \
    if [ -d /etc/ImageMagick-6 ]; then \
        install -m 644 modules/ref/policy.xml /etc/ImageMagick-6/policy.xml; \
    elif [ -d /etc/ImageMagick-7 ]; then \
        install -m 644 modules/ref/policy.xml /etc/ImageMagick-7/policy.xml; \
    else \
        install -D -m 644 modules/ref/policy.xml /etc/ImageMagick-7/policy.xml; \
    fi

VOLUME [ "/config" ]

EXPOSE 4343

# Entrypoint
CMD ["python3", "main.py", "--run", "--no-color"]
ENTRYPOINT ["bash", "./start.sh"]
