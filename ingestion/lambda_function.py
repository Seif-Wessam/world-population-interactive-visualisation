import json
import urllib.request

BUCKET = "webgis-population-app"

def get_population_data_and_country_metadata():
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
    return records_list, country_metadata
    
def enrich_population_records_with_country_info(population_records, country_metadata):

    #create a lookup dictionary for country and region information
    country_and_region_lookup = {}
    for country in country_metadata[1]:
        country_id = country.get('iso2Code')
        country_and_region_lookup[country_id] = {
            "name": country.get('name'),
            "region": country.get('region', {}).get('value'),
            "is_aggregate": country.get('region', {}).get('id') == "NA"
        }

    #fill the records_list with the region and is_aggregate information
    for record in population_records:
        country_id = record.get('country_id')
        if country_id in country_and_region_lookup:
            record['region'] = country_and_region_lookup[country_id]['region']
            record['is_aggregate'] = country_and_region_lookup[country_id]['is_aggregate']
        else:
            record['region'] = None
            record['is_aggregate'] = None

    return population_records

def s3_write_to_bucket(data, bucket_name, key):
    import boto3
    s3 = boto3.client("s3")
    serialised_data = json.dumps(data)
    response = s3.put_object(
        Bucket=bucket_name, 
        Key=key, 
        Body=serialised_data, 
        ContentType='application/json')
    return serialised_data, response["ResponseMetadata"]["HTTPStatusCode"]

def lambda_handler(event, context):
    population_records, country_metadata = get_population_data_and_country_metadata()
    enriched_records = enrich_population_records_with_country_info(population_records, country_metadata)
    body, status_code = s3_write_to_bucket(enriched_records, BUCKET, "data/enriched_population_data.json")
    return {
        'statusCode': status_code,
        'body': body
    }

if __name__ == "__main__":
    lambda_handler(None, None)

