#!/usr/bin/env python3

import os
import zipfile
import time
import argparse

# biobb common modules
from biobb_common.configuration import settings
from biobb_common.tools import file_utils as fu

# biobb pmx modules
from biobb_pmx.pmx.mutate import Mutate
from biobb_pmx.pmx.gentop import Gentop
from biobb_pmx.pmx.analyse import Analyse

# biobb md modules
from biobb_md.gromacs.pdb2gmx import Pdb2gmx
from biobb_md.gromacs.make_ndx import MakeNdx
from biobb_md.gromacs.grompp import Grompp
from biobb_md.gromacs.mdrun import Mdrun

# biobb analysis module
from biobb_analysis.gromacs.gmx_trjconv_str_ens import GMXTrjConvStrEns

def main(config, system=None):
    start_time = time.time()
    conf = settings.ConfReader(config, system)
    global_log, _ = fu.get_logs(path=conf.get_working_dir_path(), light_format=True)
    global_prop = conf.get_prop_dic(global_log=global_log)
    global_paths = conf.get_paths_dic()

    dhdl_paths_listA = []
    dhdl_paths_listB = []
    for ensemble, mutation in conf.properties['mutations'].items():
        ensemble_prop = conf.get_prop_dic(prefix=ensemble, global_log=global_log)
        ensemble_paths = conf.get_paths_dic(prefix=ensemble)


        #Create and launch bb
        global_log.info(ensemble+" Step 0: gmx trjconv: Extract snapshots from equilibrium trajectories")
        ensemble_paths['step0_trjconv']['input_traj_path'] = conf.properties['input_trajs'][ensemble]['input_traj_path']
        ensemble_paths['step0_trjconv']['input_top_path'] = conf.properties['input_trajs'][ensemble]['input_tpr_path']
        GMXTrjConvStrEns(**ensemble_paths["step0_trjconv"], properties=ensemble_prop["step0_trjconv"]).launch()


        with zipfile.ZipFile(ensemble_paths["step0_trjconv"]["output_str_ens_path"], 'r') as zip_f:
            zip_f.extractall()
            state_pdb_list = zip_f.namelist()


        for pdb_path in state_pdb_list:
            pdb_name = os.path.splitext(pdb_path)[0]
            prop = conf.get_prop_dic(prefix=os.path.join(ensemble, pdb_name), global_log=global_log)
            paths = conf.get_paths_dic(prefix=os.path.join(ensemble, pdb_name))

            #Create and launch bb
            global_log.info("Step 1: pmx mutate: Generate Hybrid Structure")
            paths['step1_pmx_mutate']['input_structure_path'] = pdb_path
            prop['step1_pmx_mutate']['mutation_list'] = mutation
            Mutate(**paths["step1_pmx_mutate"], properties=prop["step1_pmx_mutate"]).launch()

            # Step 2: gmx pdb2gmx: Generate Topology
            # From pmx tutorial:
            # gmx pdb2gmx -f mut.pdb -ff amber99sb-star-ildn-mut -water tip3p -o pdb2gmx.pdb
            global_log.info("Step 2: gmx pdb2gmx: Generate Topology")
            Pdb2gmx(**paths["step2_gmx_pdb2gmx"], properties=prop["step2_gmx_pdb2gmx"]).launch()

            # Step 3: pmx gentop: Generate Hybrid Topology
            # From pmx tutorial:
            # python generate_hybrid_topology.py -itp topol_Protein.itp -o topol_Protein.itp -ff amber99sb-star-ildn-mut
            global_log.info("Step 3: pmx gentop: Generate Hybrid Topology")
            Gentop(**paths["step3_pmx_gentop"], properties=prop["step3_pmx_gentop"]).launch()

            # Step 4: gmx make_ndx: Generate Gromacs Index File to select atoms to freeze
            # From pmx tutorial:
            # echo -e "a D*\n0 & ! 19\nname 20 FREEZE\nq\n" | gmx make_ndx -f frame0/pdb2gmx.pdb -o index.ndx
            global_log.info("Step 4: gmx make_ndx: Generate Gromacs Index file to select atoms to freeze")
            MakeNdx(**paths["step4_gmx_makendx"], properties=prop["step4_gmx_makendx"]).launch()

            if ensemble == 'stateA':
                # In stateA, with lamdda=0, we don't need the energy minimization step, so simply get the output
                # from the step2 (pdb2gmx) as output from the step6 (energy minimization)
                # From pmx tutorial:
                # There are no dummies in this state at lambda=0, therefore simply convert mut.pdb to emout.gro
                paths['step7_gmx_grompp']['input_gro_path'] = paths['step2_gmx_pdb2gmx']['output_gro_path']

            elif ensemble == 'stateB':
                # Step 5: gmx grompp: Creating portable binary run file for energy minimization
                # From pmx tutorial:
                # gmx grompp -c pdb2gmx.pdb -p topol.top -f ../../mdp/em_FREEZE.mdp -o em.tpr -n ../index.ndx
                global_log.info("Step 5: gmx grompp: Creating portable binary run file for energy minimization")
                Grompp(**paths["step5_gmx_grompp"], properties=prop["step5_gmx_grompp"]).launch()

                # Step 6: gmx mdrun: Running energy minimization
                # From pmx tutorial:
                # gmx mdrun -s em.tpr -c emout.gro -v
                global_log.info(ensemble+" Step 6: gmx mdrun: Running energy minimization")
                Mdrun(**paths["step6_gmx_mdrun"], properties=prop["step6_gmx_mdrun"]).launch()

            # Step 7: gmx grompp: Creating portable binary run file for system equilibration
            # From pmx tutorial:
            # gmx grompp -c emout.gro -p topol.top -f ../../mdp/eq_20ps.mdp -o eq_20ps.tpr -maxwarn 1
            global_log.info(ensemble+" Step 7: gmx grompp: Creating portable binary run file for system equilibration")
            Grompp(**paths["step7_gmx_grompp"], properties=prop["step7_gmx_grompp"]).launch()

            # Step 8: gmx mdrun: Running system equilibration
            # From pmx tutorial:
            # gmx mdrun -s eq_20ps.tpr -c eqout.gro -v
            global_log.info(ensemble+" Step 8: gmx mdrun: Running system equilibration")
            Mdrun(**paths["step8_gmx_mdrun"], properties=prop["step8_gmx_mdrun"]).launch()

            # Step 9: gmx grompp: Creating portable binary run file for thermodynamic integration (ti)
            # From pmx tutorial:
            # gmx grompp -c eqout.gro -p topol.top -f ../../mdp/ti.mdp -o ti.tpr -maxwarn 1
            global_log.info(ensemble+" Step 9: Creating portable binary run file for thermodynamic integration (ti)")
            Grompp(**paths["step9_gmx_grompp"], properties=prop["step9_gmx_grompp"]).launch()

            # Step 10: gmx mdrun: Running thermodynamic integration
            # From pmx tutorial:
            # gmx mdrun -s ti.tpr -c eqout.gro -v
            global_log.info(ensemble+" Step 10: gmx mdrun: Running thermodynamic integration")
            Mdrun(**paths["step10_gmx_mdrun"], properties=prop["step10_gmx_mdrun"]).launch()
            if ensemble == "stateA":
                dhdl_paths_listA.append(paths["step10_gmx_mdrun"]["output_dhdl_path"])
            elif ensemble == "stateB":
                dhdl_paths_listB.append(paths["step10_gmx_mdrun"]["output_dhdl_path"])

    #Creating zip file containing all the dhdl files
    dhdlA_path = 'dhdlA.zip'
    dhdlB_path = 'dhdlB.zip'
    fu.zip_list(dhdlA_path, dhdl_paths_listA)
    fu.zip_list(dhdlB_path, dhdl_paths_listB)

    # Step 11: pmx analyse: Calculate free energies from fast growth thermodynamic integration simulations
    # From pmx tutorial:
    # python analyze_dhdl.py -fA ../stateA/frame*/dhdl*.xvg -fB ../stateB/frame*/dhdl*.xvg --nbins 25 -t 293 --reverseB
    global_log.info(ensemble+" Step 11: pmx analyse: Calculate free energies from fast growth thermodynamic integration simulations")
    global_paths["step11_pmx_analyse"]["input_A_xvg_zip_path"]=dhdlA_path
    global_paths["step11_pmx_analyse"]["input_B_xvg_zip_path"]=dhdlB_path
    Analyse(**global_paths["step11_pmx_analyse"], properties=global_prop["step11_pmx_analyse"]).launch()

    elapsed_time = time.time() - start_time
    global_log.info('')
    global_log.info('')
    global_log.info('Execution successful: ')
    global_log.info('  Workflow_path: %s' % conf.get_working_dir_path())
    global_log.info('  Config File: %s' % config)
    if system:
        global_log.info('  System: %s' % system)
    global_log.info('')
    global_log.info('Elapsed time: %.1f minutes' % (elapsed_time/60))
    global_log.info('')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Based on the official PMX tutorial")
    parser.add_argument('--config', required=True)
    parser.add_argument('--system', required=False)
    args = parser.parse_args()
    main(args.config, args.system)
