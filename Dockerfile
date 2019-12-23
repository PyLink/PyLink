FROM python:3-alpine

RUN adduser -D -H -u 10000 pylink

VOLUME /pylink

COPY . /pylink-src

RUN cd /pylink-src && pip3 install --no-cache-dir -r requirements-docker.txt
RUN cd /pylink-src && python3 setup.py install
RUN rm -r /pylink-src

USER pylink
WORKDIR /pylink

# Run in no-PID file mode by default
CMD ["pylink", "-n"]
