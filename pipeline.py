import os
import sys
import re
import glob
import shutil
import logging
from datetime import datetime as date
from ConfigParser import SafeConfigParser
import subprocess


def correct_permissions(directory):
	"""
	Gives write privileges to the biocomp group (if not already there)
	Recurses through all directories and files underneath the path passed as the argument
	"""
	logging.info('Changing permissions on all directories underneath %s' % directory)
	os.chmod(directory, 0775)
	for root, dirs, files in os.walk(directory):
		for d in dirs:
			os.chmod(os.path.join(root, d), 0775)
		for f in files:
			os.chmod(os.path.join(root, f), 0775)


class Pipeline(object):

	def __init__(self):
		pass


	def parse_config_file(self):
		"""
		This function finds and parses a configuration file, which contains various constants to run this pipeline
		"""
		current_dir = os.path.dirname(os.path.realpath(__file__)) # this gets the directory of this script
		cfg_files = [os.path.join(current_dir, f) for f in os.listdir(current_dir) if f.endswith('cfg')]
		if len(cfg_files) == 1:
			logging.info('Parsing configuration file: %s' % cfg_files[0])
			parser = SafeConfigParser()
			parser.read(cfg_files[0])

			self.config_params_dict = {}
			for opt in parser.options(self.instrument):
				value = parser.get(self.instrument, opt)
				self.config_params_dict[opt] = value
			logging.info('Parameters parsed from configuration file: ')
			logging.info(self.config_params_dict)
		else:
			logging.error('There were %d config (*cfg) files found in %s.  Need exactly 1.  Correct this.' % (len(cfg_files), current_dir))
			sys.exit(1)


	def create_output_directory(self):
		"""
		This method takes a path to the sequencing run directory and attempts to create an output
		directory for the bcl2fastq2 output.  If it cannot (due to write permissions, etc)
		then it exits the script and issues a message
		"""

		if os.path.isdir(self.run_directory_path):
			try:
				output_directory_path = os.path.join(self.run_directory_path, self.config_params_dict.get('demux_output_dir'))
				logging.info('Creating output directory for demux process at %s' % output_directory_path)			
				os.mkdir(output_directory_path)
				correct_permissions(output_directory_path)
				self.config_params_dict['demux_output_dir'] = output_directory_path
			except:
				logging.error('An exception occurred when attempting to create the output directory at: %s' % output_directory_path)
				sys.exit(1)
		else:
			logging.error('The path supplied as the run directory is not actually a directory.  Please check.')
			sys.exit(1)


	def execute_call(self, call_command):
		"""
		This executes the call passed via the call_command the argument.  Catches any errors in the process via the system exit code
		"""
		
		logging.info('Executing the following call to the shell:\n %s ' % call_command)
		process = subprocess.Popen(call_command, shell = True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
		while True:
			line = process.stdout.readline()
			if not line:
				break
			logging.info(line)

		process.wait()		
		if process.returncode != 0:
			logging.error('The called process had non-zero exit status.  Check the log.')
			logging.info('Return code: %s ' % process.returncode)
			sys.exit(1)


	def create_project_structure(self, project_id):
		"""
		This creates the project and sample subdirectories within the time-stamped destination directory.
		"""
		orig_project_dir_path = os.path.join(self.config_params_dict.get('demux_output_dir'), project_id)
		sample_dirs = [sd for sd in os.listdir(orig_project_dir_path) if sd.startswith(self.config_params_dict.get('sample_dir_prefix'))]
		logging.info('Creating directory for %s at %s' % (project_id, self.target_dir))
		new_project_dir = os.path.join(self.target_dir, project_id)
		try:
			os.mkdir(new_project_dir)
			logging.info('Created directory for project %s at %s' % (project_id, new_project_dir))
		except OSError as ex:
			if ex.errno == 17: # directory was already there
				logging.info('Project directory at %s was already present.' % new_project_dir)
			else:
				logging.error('There was an issue creating a directory at %s' % new_project_dir)
				sys.exit(1)
		try:
			for sample_dir in sample_dirs:
				sample_dir = os.path.join(new_project_dir, sample_dir)
				os.mkdir(sample_dir)
				logging.info('Created sample directory at %s' % sample_dir)
			# change the permissions for everything underneath this new directory (including the sample-specific directories)
			correct_permissions(new_project_dir)
		except OSError as ex:
			if ex.errno == 17: # directory was already there
				logging.warning('Sample directory at %s was already present.  Generally this should not occur, so something could be wrong.  However, if the same sample we sequenced in two or more different runs, then this is expected.  Not exiting, but check this over.' % sample_dir)
			else:
				logging.error('There was an issue creating a sample directory at %s' % sample_dir)
				sys.exit(1)


	def create_final_locations(self):
		"""
		This function creates a time-stamped directory (only year+month)
		and sets up the empty directory structure where the final FASTQ files will be
		"""	

		# for organizing projects by date:
		today = date.today()
		year = today.year
		month = today.month

		# double-check that the config file had a valid path to a directory
		if os.path.isdir(self.config_params_dict.get('destination_path')):

			# try to create the directory-- it may already exist, in which case we catch the exception and move on.
			# Any other errors encountered in creating the directory will cause pipeline to exit
			try:
				year_dir = os.path.join(self.config_params_dict.get('destination_path'), str(year))
				if not os.path.isdir(year_dir):
					os.mkdir(year_dir)
					correct_permissions(year_dir)
					logging.info('Creating new year-level directory at %s' % year_dir)
				month_dir = os.path.join(year_dir, str(month))
				if not os.path.isdir(month_dir):
					os.mkdir(month_dir)
					correct_permissions(month_dir)
					logging.info('Creating new month-level directory at %s' % month_dir)					

			except OSError as ex:
				logging.error('Exception occured:')
				logging.error(ex.strerror)
				sys.exit(1)

			# check that we do have a destination directory to go to.
			if os.path.isdir(month_dir):
				self.target_dir = month_dir
				for project_id in self.project_id_list:
					Pipeline.create_project_structure(self, project_id)
			else:
				logging.error('Target directory %s does not exist for some reason.  Maybe permissions?' % target_dir)
				sys.exit(1)
		else:
			logging.error('The path supplied as the final destination base directory is not, in fact, a directory')
			sys.exit(1)



	def run_fastqc(self):
		"""
		Finds all the fastq files in 'target_directory' and runs them through fastQC with a system call
		"""
		for project_id in self.project_id_list:
			project_dir = os.path.join(self.target_dir, project_id)
			fastq_files = []
			for root, dirs, files in os.walk(project_dir):
				for f in files:
					if f.lower().endswith('final.fastq.gz'):
						fastq_files.append(os.path.join(root, f))

			for fq in fastq_files:
				try:
					call_command = self.config_params_dict['fastqc_path'] + ' ' + fq
					subprocess.check_call(call_command, shell = True)

					# get the name of the output directory from the fastQC process:
					fastqc_dir_name = os.path.basename(fq)[:-len('.fastq.gz')] + '_fastqc'
					fastqc_dir = os.path.join(os.path.dirname(fq), fastqc_dir_name)
					correct_permissions(fastqc_dir)
				except subprocess.CalledProcessError:
					logging.error('The fastqc process on fastq file (%s) had non-zero exit status.  Check the log.' % fq)
					sys.exit(1)



	def run_demux(self):
		"""
		This writes the call for the demux process.  Uses the parent to execute the actual process.
		"""
		call_command = self.config_params_dict['demux_path'] + ' --output-dir ' + self.config_params_dict['demux_output_dir'] + ' --runfolder-dir ' + self.run_directory_path
		self.execute_call(call_command)


	def concatenate_fastq_files(self):
		"""
		This method scans the output and concatenates the fastq files for each sample and read number.
		That is, the NextSeq output (in general) has a fastq file for each lane and sample and we need to 
		concatenate the lane files into a single fastq file for that sample.  For paired-end protocol, need
		to do this for both the R1 and R2 reads.
		"""

		for project_id in self.project_id_list:

			project_dir = os.path.join(self.config_params_dict.get('demux_output_dir'), project_id)

			# get the sample-specific subdirectories and append the path to the project directory in front (for full path name):
			# this gives the fully qualified location of the original fastq files (by lane)
			sample_dirs = [os.path.join(project_dir, d) for d in os.listdir(project_dir) if d.startswith(self.config_params_dict.get('sample_dir_prefix'))] 

			# double check that they are actually directories:
			sample_dirs = filter( lambda x: os.path.isdir(x), sample_dirs)

			for sample_dir in sample_dirs:
				# since bcl2fastq2 renames the fastq files with a different scheme, extract the sample name we want via parsing the directory name
				sample_name_with_prefix = os.path.basename(sample_dir)
				sample_name = sample_name_with_prefix[len(self.config_params_dict.get('sample_dir_prefix')):]

				# get all the fastq files as lists.  Note the sort so they are concatenated in the same order for paired-end protocol
				read_1_fastq_files = sorted(glob.glob(os.path.join(sample_dir, '*R1_001.fastq.gz')))			
				read_2_fastq_files = sorted(glob.glob(os.path.join(sample_dir, '*R2_001.fastq.gz'))) # will be empty list [] if single-end protocol

				paired = False
				if len(read_2_fastq_files) > 0:
					paired = True

				# need at least the read 1 files to continue
				if len(read_1_fastq_files) == 0:
					logging.error('Did not find any fastq files in %s directory.' % sample_dir)
					sys.exit(1)			

				# make file names for the merged files:
				merged_read_1_fastq = sample_name + '_R1_.' + self.config_params_dict.get('tmp_fastq_tag') + '.fastq.gz'
				merged_read_2_fastq = sample_name + '_R2_.' + self.config_params_dict.get('tmp_fastq_tag') + '.fastq.gz'

				# construct full paths to the final files:
				merged_read_1_fastq = os.path.join(self.target_dir, project_id, sample_name_with_prefix, merged_read_1_fastq)
				merged_read_2_fastq = os.path.join(self.target_dir, project_id, sample_name_with_prefix, merged_read_2_fastq)

				# an inline method to compose the concatenation command:
				write_call = lambda infiles,outfile: 'cat '+ ' '.join(infiles) + ' >' + outfile

				call_list = []
				call_list.append(write_call(read_1_fastq_files, merged_read_1_fastq))
				if len(read_2_fastq_files) > 0:
					if len(read_2_fastq_files) == len(read_1_fastq_files):
						call_list.append(write_call(read_2_fastq_files, merged_read_2_fastq))
					else:
						logging.error('Differing number of FASTQ files between R1 and R2')
						sys.exit(1)

				for call in call_list:
					try:
						logging.info('Issuing system command: %s ' % call)
						subprocess.check_call( call, shell = True )
						os.chmod(merged_read_1_fastq, 0775)	
						if paired:
							os.chmod(merged_read_2_fastq, 0775)	
					except subprocess.CalledProcessError:
						logging.error('The concatentation of the lane-specific fastq files failed somehow')
						sys.exit(1)


	def merge_and_rename_fastq(self, sample_dir, read_num):

		sample_name_with_prefix = os.path.basename(sample_dir)
		sample_name = sample_name_with_prefix[len(self.config_params_dict.get('sample_dir_prefix')):]

		k = str(read_num)
		new_read_fastq = os.path.join(sample_dir, sample_name + '_R' + k + '_.' + self.config_params_dict.get('tmp_fastq_tag') + '.fastq.gz') # the new fastq file created during this demux

		# the expected names of the final fastq files
		existing_read_k_fastq = os.path.join(sample_dir, sample_name + '_R'+ k + '_.' + self.config_params_dict.get('final_fastq_tag') +'.fastq.gz')

		if os.path.isfile(existing_read_k_fastq):
			# concatenate the existing final fastq with the new one.  Dump the result into a temp file and then rename the tempfile

			# first, rename the fastq file from this demux process to indicate which 'run' it came from
			j = len(glob.glob(os.path.join(sample_dir, sample_name + '_R' + k +"_.fc[0-9]*.fastq.gz")))
			run_specific_fq = os.path.join(sample_dir, sample_name + '_R'+ k +'_.fc' + str(j+1) + '.fastq.gz')
			os.rename(new_read_fastq, run_specific_fq)  

			# a placeholder file to concatenate into (cannot concatenate into *final.fastq.gz since that is one of the files 'providing' data to the stream
			tmpfile = os.path.join(sample_dir, sample_name + '_R'+ k + '_.tmp')
			cat_cmd = 'cat ' + existing_read_k_fastq + ' ' + run_specific_fq + '> ' + tmpfile
			self.execute_call(cat_cmd)

			# rename this 'final' fastq
			os.rename(tmpfile, existing_read_k_fastq) 
		else:
			# an existing 'final' fastq file does not exist- simply create a symlink.  This way we retain the original fastq file from each run for the sample.  Renaming
			# would cause us to lose track of which fastq file corresponds to which run
			run_specific_fq = os.path.join(sample_dir, sample_name + '_R'+ k +'_.fc1.fastq.gz')
			os.rename(new_read_fastq, run_specific_fq)  
			os.symlink(run_specific_fq, existing_read_k_fastq)



	def merge_with_existing_fastq_files(self):
		"""
		This method handles the case where the same sample has been sequenced on multiple flowcells (e.g. for extra-deep sequencing)
		It looks for existing fastq files in the final directory and concatentates this new fastq file with those, if applicable.  
		"""
		for project_id in self.project_id_list:
			sample_dirs = [os.path.join(self.target_dir, d) for d in os.listdir(os.path.join(self.target_dir, project_id)) if d.startswith(self.config_params_dict.get('sample_dir_prefix'))] 

			# double check that they are actually directories:
			sample_dirs = filter( lambda x: os.path.isdir(x), sample_dirs)

			for sample_dir in sample_dirs:
				self.merge_and_rename_fastq(sample_dir, 1)
				if len(glob.glob(os.path.join(sample_dir, '*_R2_*.fastq.gz'))) > 0:
					self.merge_and_rename_fastq(sample_dir, 2)



class NextSeqPipeline(Pipeline):
	
	def __init__(self, run_directory_path):
		self.run_directory_path = run_directory_path
		self.instrument = 'nextseq'

	def run(self):
		Pipeline.parse_config_file(self)
		Pipeline.create_output_directory(self)

		# parse out the projects and also do a check on the SampleSheet.csv to ensure the correct parameters have been entered
		self.check_samplesheet()

		# actually start the demux process:
		Pipeline.run_demux(self)
	
		# sets up the directory structure for the final, merged fastq files.
		Pipeline.create_final_locations(self)

		# the NextSeq has each sample in multiple lanes- concat those
		Pipeline.concatenate_fastq_files(self)

		# handle concatenation of these new fastq files with those that may already exist (in the case of same sample on multiple flowcells)
		Pipeline.merge_with_existing_fastq_files(self)
	
		# run the fastQC process:
		Pipeline.run_fastqc(self)



	def line_is_valid(self, line):
		"""
		Receives a sample annotation line from the Illumina-generated SampleSheet.csv and does some quick checks to see
		that the Samplesheet.csv has the correct formatting for our pipelines.
		Returns a boolean: True is all the fields are within guidelines, otherwise False
		"""
		elements = line.split(',')

		# establish a greedy regex for only letters, numbers, and underscores.  No other characters allowed.
		pattern = re.compile('[a-z0-9_]+', re.IGNORECASE)

		try:
			tests = []
			tests.append(pattern.match(elements[1]).group() == elements[1]) # if the greedy regex did not match the sample name, then something is wrong.
			tests.append(elements[0].startswith(self.config_params_dict.get('sample_dir_prefix'))) # check that the Sample_ID field has the proper prefix
			tests.append(elements[0][len(self.config_params_dict.get('sample_dir_prefix')):] == elements[1]) # check that the sample names match between the first and second fields
			tests.append(len(elements[5]) == 7) # check that 7bp index was provided
			tests.append(pattern.match(elements[6]).group() == elements[6]) # if the greedy regex did not match the full project designation then something is wrong.
			return all(tests)
		except Exception:
			return False



	def check_samplesheet(self):
		"""
		This method checks for a samplesheet and does a quick check that it is formatted within guidelines (described elsewhere)
		Returns a list of the Project identifiers.
		"""
		samplesheet_path = os.path.join(self.run_directory_path, 'SampleSheet.csv')
		logging.info('Examining samplesheet at: %s' % samplesheet_path)

		if os.path.isfile(samplesheet_path):
			# the following regex extracts the sample annotation section, which is started by '[Data]'
			# and continues until it reaches another section (or the end of the file)
			# re.findall() returns a list-- get the first element
			try:
				sample_annotation_section = re.findall(r'\[Data\][^\[]*', open(samplesheet_path).read())[0]
			except IndexError:
				logging.error('Could not find the [Data] section in the SampleSheet.csv file')
				sys.exit(1)
	 
			# this statement gets us a list, where each item in the list is the annotation line in the sample sheet.  
			# The [2:] index removes the '[Data]' and the line with the field headers 
			# Also strips off any Windows/Mac endline characters ('\r') if present
			annotation_lines = [line.rstrip('\r') for line in sample_annotation_section.split('\n') if len(line)>0][2:]

			# a list of True/False on whether the sample annotation line is valid
			lines_valid = [self.line_is_valid(line) for line in annotation_lines]
			if not all(lines_valid):
				problem_lines = [i+1 for i,k in enumerate(lines_valid) if k == False]
				logging.error('There was some problem with the SampleSheet.csv')
				logging.error('Problem lines: %s' % problem_lines)
				sys.exit(1)

			# now get a list of all the projects that we are processing in this sampling run:
			project_id_list = list(set([line.split(',')[6] for line in annotation_lines]))

			logging.info('The following projects were identified from the SampleSheet.csv: %s' % project_id_list)
			self.project_id_list = project_id_list
		else:
			logging.error('Could not locate a SampleSheet.csv file in %s ' % self.run_directory_path)
			sys.exit(1)




					

class HiSeqPipeline(Pipeline):
	
	def __init__(self, run_directory_path):
		self.run_directory_path = run_directory_path
		self.instrument = 'hiseq'

	def run(self):
		Pipeline.parse_config_file(self)
		Pipeline.create_output_directory(self)

		# parse out the projects and also do a check on the SampleSheet.csv to ensure the correct parameters have been entered
		self.check_samplesheet()

		# actually start the demux process:
		Pipeline.run_demux(self)
	
		# sets up the directory structure for the final, merged fastq files.
		Pipeline.create_final_locations(self)

		# the NextSeq has each sample in multiple lanes- concat those
		Pipeline.concatenate_fastq_files(self)
	
		# run the fastQC process:
		Pipeline.run_fastqc(self)


	def check_samplesheet(self):
		"""
		This method checks for a samplesheet and does a quick check that it is formatted within guidelines (described elsewhere)
		"""

		samplesheet_path = os.path.join(self.run_directory_path, 'SampleSheet.csv')
		logging.info('Examining samplesheet at: %s' % samplesheet_path)
		if os.path.isfile(samplesheet_path):
			# the following regex extracts the sample annotation section, which is started by '[Data]'
			# and continues until it reaches another section (or the end of the file)
			# re.findall() returns a list-- get the first element
			try:
				sample_annotation_section = re.findall(r'\[Data\][^\[]*', open(samplesheet_path).read())[0]
			except IndexError:
				logging.error('Could not find the [Data] section in the SampleSheet.csv file')
				sys.exit(1)

			# this statement gets us a list, where each item in the list is the annotation line in the sample sheet.
			# The [2:] index removes the '[Data]' and the line with the field headers
			# Also strips off any Windows/Mac endline characters ('\r') if present
			annotation_lines = [line.rstrip('\r') for line in sample_annotation_section.split('\n') if len(line)>0][2:]

			# now get a list of all the projects that we are processing in this sampling run:
			project_id_list = list(set([line.split(',')[7] for line in annotation_lines]))
			logging.info('The following projects were identified from the SampleSheet.csv: %s' % project_id_list)
			self.project_id_list = project_id_list
		else:
			logging.error('Could not locate a SampleSheet.csv file in %s ' % self.run_directory_path)
			sys.exit(1)
	









