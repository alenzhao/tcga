#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# Copyright (c) 2016--, Gregory Poore.
#
# Distributed under the terms of the Modified BSD License.
#
# ----------------------------------------------------------------------------
import numpy as np
import pandas as pd
import sevenbridges as sbg
import glob, sys, getopt, os, json, unicodedata, argparse, time
from pandas.io.json import json_normalize
from tqdm import tqdm # progressbar
from tqdm import trange

parser = argparse.ArgumentParser(description="""
	Grab TCGA metadata using CGC Sevenbridges API and summarize output into QIIME mapping file. Note that the API calling is limited
	to 1000 calls per 5 minutes (as of Aug, 2016). Projects containing more than 1000 files will thus experience pauses between 
	metadata calls, giving a minimum wall-time of ~(#files*5)/1000 minutes; projects with less than 1000 files will run normally.
	"""
	)
parser.add_argument('-o', '--outputFilePath', 
	help = 'Enter output file path (ending in /)', 
	default = './', 
	dest = 'outputFilePath')
parser.add_argument('-p', '--cgcProjectName', 
	help = 'Enter name of CGC Sevenbridges project. Note that project names CANNOT contain underscores ("_") but can contain dashes ("-"), 
	default = 'cgc-metadata-to-qiime-mapping-file-project',
	dest = 'cgcProjectName')
parser.add_argument('-u', '--cgcUserName', 
	help = 'Enter name of CGC Sevenbridges user name', 
	default = 'gregpoore',
	dest = 'cgcUserName')
parser.add_argument('-f', '--filenameSuffix',
	help = 'Enter new filename suffix (e.g. if converting from BAM files to Fasta files enter ".fasta" ',
	default = '.fasta',
	dest = 'filenameSuffix')
# parser.add_argument('-m', '--metadataFilter',
# 	help = 'Enter ')
# parser.add_argument('-d', '--diseaseTypeList', help = 'Enter desired disease name from which to pull metadata (surround with "")',
#  default = '', required=True, nargs='+', dest='diseaseTypeList', choices = ['Cholangiocarcinoma', 'Lymphoid Neoplasm Diffuse Large B-cell Lymphoma', 'Uterine Carcinosarcoma',
# 'Adrenocortical Carcinoma', 'Mesothelioma', 'Uveal Melanoma', 'Thymoma', 'Kidney Chromophobe', 'Testicular Germ Cell Tumors',
# 'Pancreatic Adenocarcinoma', 'Pheochromocytoma and Paraganglioma', 'Sarcoma', 'Rectum Adenocarcinoma', 'Glioblastoma Multiforme', 
# 'Kidney Renal Papillary Cell Carcinoma','Cervical Squamous Cell Carcinoma and Endocervical Adenocarcinoma', 'Acute Myeloid Leukemia',
# 'Esophageal Carcinoma', 'Liver Hepatocellular Carcinoma', 'Skin Cutaneous Melanoma', 'Bladder Urothelial Carcinoma', 
# 'Brain Lower Grade Glioma', 'Stomach Adenocarcinoma', 'Prostate Adenocarcinoma', 'Thyroid Carcinoma', 'Lung Squamous Cell Carcinoma',
# 'Lung Adenocarcinoma', 'Colon Adenocarcinoma', 'Head and Neck Squamous Cell Carcinoma', 'Uterine Corpus Endometrial Carcinoma',
# 'Kidney Renal Clear Cell Carcinoma', 'Ovarian Serous Cystadenocarcinoma', 'Breast Invasive Carcinoma'])
args = parser.parse_args()
outputFilePath = args.outputFilePath
cgcProjectName = args.cgcProjectName
cgcUserName = args.cgcUserName
filenameSuffix = args.filenameSuffix
# diseaseTypeList = args.diseaseTypeList

# #['-o', '--outputFilePath', '-p','--cgcProjectName', '-u', '--cgcUserName', '-d', '--diseaseTypeList']

print("\n")
print("Output directory         :%r" % outputFilePath)
print("CGC project name         :%r" % cgcProjectName)
print("CGC user name            :%r" % cgcUserName)

# Use config file for login. See here if you have questions: 
# https://github.com/sbg/okAPI/blob/aa8a097c6f0be24170b0a0c800460c6defd0d6c9/Recipes/SBPLAT/Setup_API_environment.ipynb
config_file = sbg.Config(profile='cgc')
api = sbg.Api(config=config_file)

print("\n")
print("Grabbing list of files, their names, and IDs...")
# Grab list of files, their names and IDs
file_list = api.files.query(
    project=cgcUserName+'/'+cgcProjectName)
print("Extracting file names...")
f_names = [f.name for f in file_list.all()] # Grab filenames
print("Extracting file IDs...")
f_id = [f.id for f in file_list.all()] # Grab file IDs

# Grab and store filenames; convert from Unicode to Python strings
filenames = []
for ind, val in enumerate(f_names):
    filenames.append(unicodedata.normalize('NFKD', f_names[ind]).encode('latin-1','ignore').decode("utf-8"))

# Store filename strings in DF
filenamesDF = pd.DataFrame(filenames, columns = ['filename'])

# Add column of filenames with new suffixes
filenamesNewSuffix = [os.path.splitext(x)[0]+filenameSuffix for x in filenames]
filenamesDF["filenames_new_suffix"] = filenamesNewSuffix

print("Grabbing files' metadata...")
# Grab metadata for files of desired disease type
metaList = []
delayToggle = False
safetyFactor = 1.05 # 5% margin for time delay

if len(f_id) >= 1000:
    multiplier = len(f_id)/1000
    delayToggle = True
    print("More than a 1000 files requested. API calling limits will cause delays...")
for k in trange(0,len(f_id)):
    metadataFile = json_normalize(api.files.get(id=f_id[k]).metadata)
    metaList.append(metadataFile) ## store dataframes in list
    if delayToggle == True:
        time.sleep(0.3*safetyFactor) 
        # Explanation: Assuming the metadata call is very quick for one file,
        # the loop must be delayed to iterate at a maximum speed of of 0.3 seconds/file.
        # The reasoning is that a 1000 API calls per 5 minutes allows a maximum
        # rate of 1000/(5*60) = 3.33 files/second, or 0.3 seconds/file.

# Merge lists together to form Pandas DF
metaDF = pd.concat(metaList, axis=0, ignore_index=True)

# Merge with filenames DF
joinedMetaDF = pd.concat([filenamesDF, metaDF], axis=1)
joinedMetaDF = joinedMetaDF.fillna("NA") # Replace missing values with "NA" for QIIME; note that Python normally shows "NaN"

#-------------------------Make QIIME Mapping File--------------------------#
print("Making QIIME mapping file...")
# Generate sampleIDs
sampleIDList = []
for ind in range(0, len(f_id)):
	sampleIDList.append('s'+str(ind))
    
# Start creating QIIME mapping file format. See the following link for more details:
# http://qiime.org/documentation/file_formats.html
sampleIDsDF = pd.DataFrame(sampleIDList, columns = ['#SampleID'])
sampleIDsDF["BarcodeSequence"] = ""
sampleIDsDF["LinkerPrimerSequence"] = ""
qiimeDF = pd.concat([sampleIDsDF, joinedMetaDF], axis=1)
qiimeDF["Description"] = qiimeDF['#SampleID'] + "__" + qiimeDF['filename']

# Convert case_uuid to lowercase to align with GDC portal (https://gdc-portal.nci.nih.gov/search/s)
qiimeDF["case_uuid"] = qiimeDF["case_uuid"].str.lower()

# Create mapping text file (tab-delimited)
outputFilePathName = outputFilePath + 'cgc_qiime_mapping_file.txt'
qiimeDF.to_csv(outputFilePathName, sep="\t", index=False)
print("QIIME mapping file saved to output directory!")
