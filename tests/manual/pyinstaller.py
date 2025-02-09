from time import sleep

if __name__ == "__main__":
    try:
        print("Started the test executable...")  # noqa: T201

        while True:
            sleep(1.0)
    except KeyboardInterrupt:
        print("Caught KeyboardInterrupt")  # noqa: T201
