import yaml

def test():
    with open("emon_config.yml", 'r') as f:
        documents = yaml.full_load(f)

        for item, doc in documents.items():
            print(item, ":", doc)
        print(documents['rain'][0]['name'])

test()