import json
import urllib.request

BUCKET = "webgis-population-app"

def lambda_handler(event, context):
    url =  "https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL?format=json&per_page=300&mrv=1"
    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read())
    # Response: [metadata dictionary, list of population records]
    # Each record contains:
    #   country.value: country or region name
    #   date: year as a string
    #   value: population, possibly None
    records = data[1]
    # each record is a dict:
        #indicator: dict keys: id, value
        #country: dict keys: id, value
        #"countryiso3code": "",
        #"date": "",
        #"value": int,
        #"unit": "",
        #"obs_status": "",
        #"decimal": int
    records_list = []
    for record in records:
        country = record['country']['value']
        country_id = record['country']['id']
        date = record['date']
        population_value = record['value']
        record_dict = {
            "country": country,
            "country_id": country_id,
            "date": date,
            "population": population_value
        }
        records_list.append(record_dict)

    #the goal now is to establish a connection to the same API 
    #so that we get the metadata of the different countries
    #to differentiate a country from a regional aggregation
    metadata_url =  "https://api.worldbank.org/v2/country?format=json&per_page=300&mrv=1"
    with urllib.request.urlopen(metadata_url) as response:
        country_metadata = json.loads(response.read())
    # Response: [metadata dictionary, list of population records]
    # Each population record contains:
    #dict keys: 
    #   id, str 
    #   iso2Code, str 
    #   name, str
    #   region, dict keys: id, iso2code, value
    #   adminregion, dict keys: id, iso2code, value
    #   incomeLevel, dict keys: id, value
    #   lendingType, dict keys: id, value
    #   capitalCity, str
    #   longitude, float
    #   latitude, float
    country_and_region_lookup = {}
    for country in country_metadata[1]:
        country_id = country.get('iso2Code')
        country_and_region_lookup[country_id] = {
            "name": country.get('name'),
            "region": country.get('region', {}).get('value'),
            "is_aggregate": country.get('region', {}).get('id') == "NA"
        }

    #now we can fill the records_list with the region and is_aggregate information
    for record in records_list:
        country_id = record.get('country_id')
        if country_id in country_and_region_lookup:
            record['region'] = country_and_region_lookup[country_id]['region']
            record['is_aggregate'] = country_and_region_lookup[country_id]['is_aggregate']
        else:
            record['region'] = None
            record['is_aggregate'] = None

    return {
        'statusCode': 200,
        'body': json.dumps('Hello from Lambda!')
    }

if __name__ == "__main__":
    lambda_handler(None, None)