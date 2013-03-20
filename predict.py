#!/usr/bin/python
# Requires Python 2.7

"""
March Madness prediction script
Copyright (C) 2013 Kyle Barlow

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

# Python import statements
import argparse
import os
import sys
import operator
import random
import time
from multiprocessing import Pool

# Constants
program_description='Python script to auto-generate "quick pick" march madness brackets from probability input (as in the format of, but not necessarily, the 538 data from Nate Silver)\nEach probability input is assumed to be built up conditionally'

default_input_file='data.csv'
default_output_file='output.txt'

# Expected header string
header_string='REGION,SEED,TEAM,FIRST FOUR,ROUND OF 32,ROUND OF 16,ELITE 8,FINAL 4,FINALS,CHAMPIONS'

# Mapping for strings describing each round to an integer (for indexing)
# Counting starts with 1
round_dictionary={
1:'FIRST FOUR',
2:'ROUND OF 32',
3:'ROUND OF 16',
4:'ELITE 8',
5:'FINAL 4',
6:'FINALS',
7:'CHAMPIONS'
}

max_region_round=5

num_champion_simulation_runs=20000
desired_champion_simulation_runs=10000

# Classes
class Reporter:
    def __init__(self,task):
        self.start=time.time()
        self.lastreport=self.start
        self.task=task
        self.report_interval=1 # Interval to print progress (seconds)
        print 'Starting '+task
    def report(self,n):
        t=time.time()
        if self.lastreport<(t-self.report_interval):
            self.lastreport=t
            sys.stdout.write("  Completed: "+str(n)+" simulation runs\r" )
            sys.stdout.flush()
    def done(self):
        print 'Done %s, took %.3f seconds\n' % (self.task,time.time()-self.start)

# Class to generalize multiprocessing pools
class MultiWorker:
    def __init__(self,task,func,custom_cb_func=None):
        self.reporter=Reporter(task)
        self.func=func
        self.pool=Pool()
        self.results_dict={}
        self.custom_cb_func=custom_cb_func
        if custom_cb_func==None:
            self.custom_cb_enabled=False
        else:
            self.custom_cb_enabled=True
        self.count=0
    def cb(self,t):
        self.results_dict[t[0]]=t[1]
        self.reporter.report(len(self.results_dict))
    def custom_cb(self,t):
        self.count+=1
        self.reporter.report(self.count)
        self.custom_cb_func(t)
    def addJob(self,argsTuple):
        if self.custom_cb_enabled:
            self.pool.apply_async(self.func,argsTuple,callback=self.custom_cb)
        else:
            self.pool.apply_async(self.func,argsTuple,callback=self.cb)
    def finishJobs(self):
        self.pool.close()
        self.pool.join()
        self.reporter.done()
        return self.results_dict

class Team:
    # Stores information on a team's probabilities of advancing to each round
    def __init__(self,name,region,seed,round_odds,conditional_round_odds,seed_slot):
        self.region=region
        self.seed=seed
        self.name=name
        self.round_odds=round_odds
        self.conditional_round_odds=conditional_round_odds

        # If a team beats a higher seed, this variable is used
        #  to store the higher team's seed
        self.seed_slot=seed_slot

    @classmethod
    def init_from_line(cls, team_line):
        line_data=team_line.split(',')
        region=line_data[0]
        seed=int(line_data[1])
        name=line_data[2]
        round_odds=[]
        for item in line_data[3:10]:
            if item=='':
                round_odds.append(None)
            elif item=='<0.1':
                round_odds.append(.0001)
            else:
                round_odds.append(float(item))

        # Make the probabilities conditional
        conditional_round_odds=[]
        for i,odd in enumerate(round_odds):
            if i==0:
                conditional_round_odds.append(odd)
            else:
                prev_round=round_odds[i-1]
                if prev_round==None:
                    conditional_round_odds.append(odd)
                else:
                    conditional_round_odds.append(odd/prev_round)

        return cls(name,region,seed,round_odds,conditional_round_odds,seed)

    def copy(self):
        # Returns all duplicate (should be non-mutated) objects, except for resets seed slot
        return Team(self.name,self.region,self.seed,self.round_odds,self.conditional_round_odds,self.seed)

    def __getitem__(self,i):
        return self.round_odds[i-1] # Rounds are indexed from 1; lists from 0

    def __repr__(self):
        return self.name

    def __lt__(self, other):
         return self.seed < other.seed

    def reset_seed_slot(self):
        self.seed_slot=self.seed

class SimulateDesiredChampionResults:
    def __init__(self):
        self.region_counts={}
        self.finalist_counts={}

    def cb(self,tup):
        run_number,results_bracket=tup
        for region in results_bracket:
            region_name=str(region)
            if region_name not in self.region_counts:
                self.region_counts[region_name]={}
            for round_number in region.teams_by_round:
                if round_number not in self.region_counts[region_name]:
                    self.region_counts[region_name][round_number]={}
                for team in region.teams_by_round[round_number]:
                    team=str(team)
                    if team not in self.region_counts[region_name][round_number]:
                        self.region_counts[region_name][round_number][team]=0
                    self.region_counts[region_name][round_number][team]+=1

        for team in results_bracket.finalists:
            team=str(team)
            if team not in self.finalist_counts:
                self.finalist_counts[team]=0
            self.finalist_counts[team]+=1
        

class Region:
    # Stores a region of the bracket and all team data for that region
    def __init__(self,name,teams,teams_by_round):
        self.name=name
        self.teams=teams
        # After simulation, this dictionary stores the teams that are in each round
        #  Key: round number
        #  Value: list of team objects
        self.teams_by_round=teams_by_round

    @classmethod
    def init_empty(cls, name):
        return cls(name,[],{})

    def copy(self):
        # Does not copy simulation results stored in teams_by_round
        teams=[]
        for team in self.teams:
            teams.append(team.copy())
        return Region(self.name,teams,{})

    def __repr__(self):
        return self.name

    def append(self,team):
        self.teams.append(team)

    def __iter__(self):
        return self.teams.__iter__()

    def sort(self):
        self.teams.sort(key=operator.attrgetter('seed'))

    def reset_seed_slots(self):
        for team in self.teams:
            team.reset_seed_slot()

    def simulate(self):
        self.teams_by_round={}
        self.reset_seed_slots()
        # Simulate beginning of round of 32 by removing duplicate seeds (first 4)
        round2_teams={}
        for team in self.teams:
            if team.seed not in round2_teams:
                round2_teams[team.seed]=[]
            round2_teams[team.seed].append(team)
        for seed in round2_teams:
            teams=round2_teams[seed]
            if len(teams)==2:
                round2_teams[seed]=[pick_winner(teams[0],teams[1],1)]
            elif len(teams)!=1:
                raise Exception('Incorrect number of teams for seed %d'%(seed))
        self.teams_by_round[1]=[i[0] for i in round2_teams.values()]

        # Now iterate through the rest of the rounds
        for round_number in xrange(2,max_region_round+1):
            this_round_teams=[]

            prev_round_teams=self.teams_by_round[round_number-1]
            prev_round_teams.sort(key=operator.attrgetter('seed_slot'))
            half_num_teams=len(prev_round_teams)/2

            high_seeds=prev_round_teams[:half_num_teams]
            low_seeds=prev_round_teams[half_num_teams:]
            low_seeds.sort(key=operator.attrgetter('seed_slot'),reverse=True)

            for team1,team2 in zip(high_seeds,low_seeds):
                this_round_teams.append(pick_winner(team1,team2,round_number))
            
            this_round_teams.sort(key=operator.attrgetter('seed'))
            self.teams_by_round[round_number]=this_round_teams
            
class Bracket:
    # Represents bracket and stores all region and team data
    def __init__(self,regions,finalists,champion):
        self.regions=regions
        self.finalists=finalists
        self.champion=champion

    @classmethod
    def fromfile(cls, bracket_file):
        regions={}
        with open(bracket_file,'r') as f:
            lines=f.readlines()
            
            # Check for correct header line
            header_line=lines[0].strip()
            if header_line!=header_string:
                print header_line
                print header_string
                raise Exception("Header line doesn't match expected format")

            # Read in team data
            for line in lines[1:]:
                team=Team.init_from_line(line.strip())
                if team.region not in regions:
                    regions[team.region]=Region.init_empty(team.region)
                    
                regions[team.region].append(team)
            
            # Sort each region list of teams by seed
            for region in regions.values():
                region.sort()

        return cls(regions,None,None)

    def copy(self):
        regions={}
        for region in self.regions:
            regions[region]=self.regions[region].copy()
        finalists=None
        if self.finalists!=None:
            finalists=[]
            for finalist in self.finalists:
                finalists.append(finalist.copy())
        champion=None
        if self.champion!=None:
            champion=self.champion.copy()
        return Bracket(regions,finalists,champion)

    def __iter__(self):
        return self.regions.values().__iter__()
  
    def simulate_champion(self,desired_champion):
        self.simulate()
        while str(self.champion)!=desired_champion:
            self.simulate()
        return self
  
    def simulate(self):
        midwest=None
        south=None
        east=None
        west=None
        # Find each region winner
        for region in self.regions.values():
            region.simulate()
            region_winner=region.teams_by_round[5][0]
            if region.name=='Midwest':
                midwest=region_winner
            elif region.name=='South':
                south=region_winner
            elif region.name=='East':
                east=region_winner
            elif region.name=='West':
                west=region_winner
            else:
                raise Exception('Region "%s" not recognized'%(region.name))
        
        # Then matchup region winners
        finalist_1=pick_winner(midwest,west,6)
        finalist_2=pick_winner(south,east,6)
        self.finalists=[finalist_1,finalist_2]

        # Now pick a champion
        self.champion=pick_winner(finalist_1,finalist_2,7)

    def simulation_string(self):
        return_string=''
        final_four=[]
        # First, build each region
        for region in self.regions.values():
            return_string+='\n==========%s==========\n'%(str(region))
            for round_number in xrange(1,max_region_round+1):
                return_string+='\n%s:\n'%(round_dictionary[round_number])
                for team in region.teams_by_round[round_number]:
                    return_string+='%s\n'%(str(team))

        # Build up finals
        return_string+='\n==========Championship==========\n'
        for team in self.finalists:
            return_string+='%s\n'%(team)
        return_string+='\nChampion: %s\n'%(self.champion)
        return return_string

    def results(self):
        return (self.regions,self.finalists,self.champion)
            

# Functions

def pick_winner(team1,team2,round_number):
    team1_prob=team1[round_number]
    team2_prob=team2[round_number]
    odds_range=team1_prob+team2_prob
    num=random.uniform(0,odds_range)
    if num<=team1_prob:
        if team2.seed<team1.seed_slot:
            team1.seed_slot=team2.seed
        return team1
    else:
        if team1.seed<team2.seed_slot:
            team2.seed_slot=team1.seed
        return team2

def simulate_desired_champion(run_number,original_bracket,desired_champion):
    bracket=original_bracket.copy()
    #print 'Started run %d'%(run_number)
    return (run_number,bracket.simulate_champion(desired_champion))

def predictor():
    # Setup argument parser
    parser = argparse.ArgumentParser(description=program_description)
    parser.add_argument('-i','--input',
                        default=default_input_file,
                        help="Input data file to read in. Header must be in a specific format")
    parser.add_argument('-o','--output',
                        default=default_output_file,
                        help="File to save output")
    parser.add_argument('-c','--champion_mode',
                        action='store_true',
                        default=False,
                        help="Does many simulations and prints out odds of each team being champion")
    parser.add_argument('-f','--find_champion',
                        default=None,
                        help="Runs the simulation until the specified champion is found")

    args=parser.parse_args()

    if args.champion_mode:
        bracket=Bracket.fromfile(args.input)
        champions={}
        for i in xrange(0,num_champion_simulation_runs):
            bracket.simulate()
            if bracket.champion not in champions:
                champions[bracket.champion]=0
            champions[bracket.champion]+=1
            
        output_list=[(champions[champion],str(champion)) for champion in champions]
        output_list.sort(reverse=True)
        
        print 'Percent chance of winning tournament:'
        for num_wins,name in output_list:
            win_percent=float(num_wins)*100/float(num_champion_simulation_runs)
            if win_percent>=1:
                print '  %s: %.1f%%'%(name,win_percent)
        
        return 0

    if args.find_champion!=None:
        desired_champion=args.find_champion
        print 'Desired champion: %s'%(desired_champion)
        bracket=Bracket.fromfile(args.input)

        results=SimulateDesiredChampionResults()

        print 'Simulation will stop after %d runs generate desired champion'%(desired_champion_simulation_runs)
        w=MultiWorker('running desired champion simulations',simulate_desired_champion,results.cb)

        for x in xrange(1,desired_champion_simulation_runs+1):
            w.addJob((x,bracket,desired_champion))

        w.finishJobs()

        #print region_counts
        print results.finalist_counts
        

        return 0
        while (True):
            if str(champion)==desired_champion:
                break
            champion=bracket.simulate_champion()
        
        print bracket.simulation_string()
        return 0

    bracket=Bracket.fromfile(args.input)
    bracket.simulate()
    sim_string=bracket.simulation_string()
    print sim_string

    with open(args.output,'w') as f:
        f.write(sim_string)

    return 0

# Main function
if __name__ == "__main__":
    sys.exit(predictor())
