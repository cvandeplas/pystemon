#
# Builder Stage
#
FROM python:3.9-alpine  AS builder

# Add needed packages
RUN apk add --update --no-cache g++ gcc libxslt-dev

# set working directory
WORKDIR /usr/src/app

# install dependencies 
COPY ./requirements.txt .
# pip wheel
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /usr/src/app/wheels -r requirements.txt


#
# Runtime Stage
#
FROM builder as RUNTIME

WORKDIR /opt/pystemon

COPY --from=builder /usr/src/app/wheels /wheels
COPY --from=builder /usr/src/app/requirements.txt .
RUN pip install --upgrade --no-cache pip
RUN pip install --no-cache /wheels/*

# copy project
COPY . /opt/pystemon

ENTRYPOINT ["/opt/pystemon/pystemon.py"]
