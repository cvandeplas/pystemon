#
# Builder Stage
#
FROM python:3.9-alpine  AS builder

# Set working directory
WORKDIR /usr/src/app

# Install dependencies 
COPY ./requirements.txt .

# Add needed packages
RUN echo "\n===> Installing apk...\n" && \
    apk add --update --no-cache g++ && \
    apk add --no-cache gcc && \
    apk add --no-cache libxslt-dev && \
    echo "\n===> Python build Wheel archives for requirements...\n" && \
    pip wheel --no-cache-dir --no-deps --wheel-dir /usr/src/app/wheels -r requirements.txt && \
    echo "\n===> Removing package list...\n" && \
    rm -rf /var/cache/apk/*


#
# Runtime Stage
#
FROM builder as RUNTIME

LABEL name="pystemon" \
      description="Monitoring tool for PasteBin-alike sites written in Python" \
      url="https://github.com/cvandeplas/pystemon" \
      maintainer="christophe@vandeplas.com"

WORKDIR /opt/pystemon

COPY --from=builder /usr/src/app/wheels /wheels

RUN echo "\n===> Custom tuning...\n" && \
    pip install --upgrade --no-cache pip && \
    pip install --no-cache /wheels/*

# copy project
COPY . /opt/pystemon
